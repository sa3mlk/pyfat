#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from datetime import datetime, date
from struct import unpack
from os import SEEK_SET

'''
Work In Progress!

TODO:
 * Read files
 * Write files
 * (Un)delete files
 * Change file attributes
 * Change file timestamps
 * Make directories
 * Add FAT12 and FAT32 support
 * Long filenames?
 * Defrag functionality?
 * Add exFAT support?
 * Extensive unit tests and preferably cross
   reference to another FAT implementation
 * More...
'''

class FAT(object):
	Version = "0.01"

	# Static constants used
	EOF_FAT12 = 0x00000ff8
	EOF_FAT16 = 0x0000fff8
	EOF_FAT32 = 0x0ffffff8
	# The size of a FAT directory entry
	DIRSIZE = 32

	class Type:
		FAT12 = 1
		FAT16 = 2
		FAT32 = 3
		exFAT = 4

	class Attribute:
		READONLY = 0x01
		HIDDEN = 0x02
		SYSTEM = 0x04
		LABEL = 0x08
		DIRECTORY = 0x10
		ARCHIVE = 0x20
		LONGNAME = READONLY | HIDDEN | SYSTEM | LABEL

	class FileNotFoundError(Exception):
		def __init__(self, path):
			self.path = path
		def __str__(self):
			return "The file or directory \"%s\" doesn't exist" % self.path

	def __init__(self, fd):
		self.fd = fd
		self.info = self.__parse_bootsector()

		# Calculate the offset to the first FAT
		self.__fat_start = self.info["reserved_sectors"] * self.info["sector_size"]
		self.fat_type, self.EOF = self.__determine_type()

		# Calculate the offset to the root directory
		self.__root_dir = ((self.info["num_fats"] * self.info["sectors_per_fat"]) *
			self.info["sector_size"]) + self.__fat_start

		# Calculate the offset to the actual data start
		self.__data_start = self.__root_dir + (FAT.DIRSIZE * self.info["root_entries"])

		#self.__dirs = self.__scan_dirs(offset=self.__root_dir + FAT.DIRSIZE)
		#for k, v in self.__dirs.iteritems():
			#print "name %-13.13s cluster %d" % (k, v["cluster"])

	# Determines which type of FAT it is depending on the properties
	def __determine_type(self):
		root_dir_sectors = ((self.info["root_entries"] * FAT.DIRSIZE) +
			(self.info["sector_size"] - 1)) / self.info["sector_size"]
		data_sectors = self.info["total_sectors"] - (self.info["reserved_sectors"] +
			(self.info["num_fats"] * self.info["sectors_per_fat"]) + root_dir_sectors)
		num_clusters = data_sectors / self.info["sectors_per_cluster"]
		if num_clusters < 4085:
			return (FAT.Type.FAT12, FAT.EOF_FAT12)
		elif num_clusters < 65525:
			return (FAT.Type.FAT16, FAT.EOF_FAT16)
		else:
			return (FAT.Type.FAT32, FAT.EOF_FAT32)

	def __next_cluster(self, cluster):
		offset = self.__fat_start
		if self.fat_type == FAT.Type.FAT12:
			offset += cluster + (cluster / 2)
		elif self.fat_type == FAT.Type.FAT16:
			offset += cluster * 2
		elif self.fat_type == FAT.Type.FAT32:
			offset += cluster * 4
		else:
			raise NotImplementedError
		self.fd.seek(offset)
		return unpack("<H", self.fd.read(2))[0]

	def get_cluster_chain(self, cluster):
		chain = [cluster]
		while cluster != self.EOF:
			chain.append(self.__next_cluster(cluster))
			cluster = chain[-1]
		return chain[:-1]

	def read_cluster(self, cluster):
		if cluster < 2:
			return ""
		self.fd.seek(self.__cluster_to_offset(cluster))
		return self.fd.read(self.info["sectors_per_cluster"] * self.info["sector_size"])

	# Calculate the logical sector number from the cluster
	def __cluster_to_offset(self, cluster):
		offset = ((cluster - 2) * self.info["sectors_per_cluster"]) * self.info["sector_size"]
		return self.__data_start + offset

	# Recursively scan all directories in the FAT image
	def __scan_dirs(self, offset, parent=""):
		items = self.__read_dir(offset)
		dirs = {}
		for i in items:
			if i["attributes"] & FAT.Attribute.DIRECTORY:
				dirs[parent + "/" + i["name"]] = i
				if i["name"] != "." and i["name"] != "..":
					subdir = self.__scan_dirs(self.__cluster_to_offset(i["cluster"]), i["name"])
					for k, v in subdir.iteritems():
						dirs["/" + k] = v
		return dirs

	# Read everything we need from the bootsector
	def __parse_bootsector(self):
		data = unpack("<3x8sHBHBHHBHHHLL", self.fd.read(36))
		return {
			"oem": data[0].strip(" "),
			"sector_size": data[1],
			"sectors_per_cluster": data[2],
			"reserved_sectors": data[3],
			"num_fats": data[4],
			"root_entries": data[5],
			"total_sectors": data[6] if data[6] != 0 else data[12],
			"media_descriptor": data[7],
			"sectors_per_fat": data[8],
			"sectors_per_track": data[9],
			"num_heads": data[10],
			"hidden_sectors": data[11]
		}

	# Convert a FAT date to a date object
	def __parse_fat_date(self, v):
		year, month, day = 1980 + (v >> 9), (v >> 5) & 0x1f, v & 0x1f
		month = min(max(month, 12), 1)
		day = min(max(day, 31), 1)
		return date(year, month, day)

	# Convert a FAT timestamp to a datetime object
	def __parse_fat_datetime(self, v1, v2, v3):
		hour, minute, second = v2 >> 11 & 0x1f, v2 >> 16 & 0x3f, (v2 & 0x1f) * 2
		if v1 > 100:
			second += 1
			v1 -= 100
		usec = v1 * 10000
		d = self.__parse_fat_date(v3)
		return datetime(d.year, d.month, d.day, hour, minute, second, usec)

	# Read and parse a FAT directory entry
	def __read_dir_entry(self):
		de = unpack("<11sBxBHHH2xHHHL", self.fd.read(FAT.DIRSIZE))
		# TODO: Handle long filenames
		if de[1] & FAT.Attribute.LONGNAME:
			return None
		else:
			return {
				"name": self.__normalize_name(de[0]),
				"attributes": de[1],
				"created": self.__parse_fat_datetime(de[2], de[3], de[4]),
				"last_accessed": self.__parse_fat_date(de[5]),
				"modified": self.__parse_fat_datetime(0, de[6], de[7]),
				"cluster": de[8],
				"size": de[9]
			}

	# Normalizes a 8.3 FAT filename
	def __normalize_name(self, fatname):
		if fatname[8:] == "   ":
			# Skip the dot if there is no file extension
			return fatname[:8].strip(" ")
		else:
			# Otherwise strip the spaces and dotify plus the extension
			return fatname[:8].strip(" ") + "." + fatname[8:]

	def __read_dir(self, offset):
		self.fd.seek(offset, SEEK_SET)
		items = []
		for i in range(self.info["root_entries"]):
			de = self.__read_dir_entry()
			if not de:
				continue
			# Skip deleted files
			if de["name"][0] == '\xe9':
				continue
			# Break when we hit the first blank filename
			elif de["name"][0] == '\x00':
				break
			else:
				items.append(de)
		return items

	def get_label(self):
		# FIXME: Is the label always located as the first file in the root directory?
		self.fd.seek(self.__root_dir, SEEK_SET)
		return unpack("11s", self.fd.read(11))[0].strip(" ")

	def read_file(self, path):
		root = self.read_dir("")
		dirs = path.split("/")
		for part in path.split("/"):
			print part
		raise NotImplementedError

	def write_file(self, path):
		raise NotImplementedError

	# Read all files from a directory
	def read_dir(self, path=""):
		# Start with the root directory
		items = self.__read_dir(self.__root_dir + FAT.DIRSIZE)
		# Filter out empty strings
		subdirs = filter(len, path.split("/"))
		# Now look in all sub directories for our path
		for d in subdirs:
			# Get the one and only directory we are looking for
			items = filter(lambda x: x["attributes"] & FAT.Attribute.DIRECTORY and x["name"].lower() == d, items)
			if not items:
				raise FAT.FileNotFoundError(path)
			items = self.__read_dir(self.__cluster_to_offset(items[0]["cluster"]))
		return items

def main():
	fat = FAT(file("fat16.bin", "rb"))
	#for k, v in fat.info.iteritems():
		#print "%-22s%s" % (k, v)
	#print ""

	dirs = [
		"",
		"dosfs",
		"euler",
		"folder",
		"folder/deep1",
		"folder/deep1/deep2",
		"folder/deep1/deep2/deep3"
	]

	for d in dirs:
		print "Contents in", d
		for f in fat.read_dir(d):
			if f["attributes"] & FAT.Attribute.DIRECTORY:
				print "%-12.12s <DIR>" % f["name"]
			else:
				print "%-12.12s %d bytes" % (f["name"], f["size"])
		print ""

	'''
	print "Files in volume \"%s\"\n" % fat.get_label()
	files = fat.read_dir("")
	for f in files:
		# Very "raw" reading for now :)
		if not f["attributes"] & FAT.Attribute.DIRECTORY:
			with file("dump/%s" % f["name"], "wb") as out:
				for c in fat.get_cluster_chain(f["cluster"]):
					out.write(fat.read_cluster(c))

		print "%-13.13s%10.d bytes" % (f["name"], f["size"]),
		print fat.get_cluster_chain(f["cluster"])
	'''

if __name__ == "__main__":
	main()

