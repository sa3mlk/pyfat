#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from datetime import datetime, date
from struct import unpack
from os import SEEK_SET

# TODO:
#  Add docstrings
#  write_file
#  etc.

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
		self.__start = fd.tell()
		self.info = self.__parse_bootsector()

		# Calculate the offset to the first FAT
		self.__fat_start = self.__start + self.info["reserved_sectors"] * self.info["sector_size"]

		self.fat_type, self.EOF, self.__num_clusters = self.__determine_type()

		# Calculate the offset to the root directory
		self.__root_dir = ((self.info["num_fats"] * self.info["sectors_per_fat"]) *
			self.info["sector_size"]) + self.__fat_start

		# Calculate the offset to the actual data start
		self.__data_start = self.__root_dir + (FAT.DIRSIZE * self.info["root_entries"])

	# Determines which type of FAT it is depending on the properties
	def __determine_type(self):
		root_dir_sectors = ((self.info["root_entries"] * FAT.DIRSIZE) +
			(self.info["sector_size"] - 1)) / self.info["sector_size"]
		data_sectors = self.info["total_sectors"] - (self.info["reserved_sectors"] +
			(self.info["num_fats"] * self.info["sectors_per_fat"]) + root_dir_sectors)
		num_clusters = data_sectors / self.info["sectors_per_cluster"]
		if num_clusters < 4085:
			return (FAT.Type.FAT12, FAT.EOF_FAT12, num_clusters)
		elif num_clusters < 65525:
			return (FAT.Type.FAT16, FAT.EOF_FAT16, num_clusters)
		else:
			return (FAT.Type.FAT32, FAT.EOF_FAT32, num_clusters)

	def __next_cluster(self, cluster):
		offset = self.__fat_start
		if self.fat_type == FAT.Type.FAT12:
			offset += cluster + (cluster / 2)
			self.fd.seek(offset, SEEK_SET)
			value = unpack("<H", self.fd.read(2))[0]
			return value >> 4 if cluster & 1 else value & 0xfff
		elif self.fat_type == FAT.Type.FAT16:
			offset += cluster * 2
			self.fd.seek(offset, SEEK_SET)
			return unpack("<H", self.fd.read(2))[0]
		elif self.fat_type == FAT.Type.FAT32:
			offset += cluster * 4
			self.fd.seek(offset, SEEK_SET)
			return unpack("<L", self.fd.read(4))[0]
		else:
			raise NotImplementedError

	def next_free_cluster(self, start=2):
		for i in range(start, self.__num_clusters):
			cluster = self.__next_cluster(i)
			if cluster == 0:
				return i
		return self.EOF

	def get_cluster_chain(self, cluster):
		chain = [cluster]
		if cluster == 0:
			return chain
		while cluster < self.EOF:
			chain.append(self.__next_cluster(cluster))
			cluster = chain[-1]
		return chain[:-1]

	def read_cluster(self, cluster):
		if cluster < 2:
			return ""
		self.fd.seek(self.cluster_to_offset(cluster))
		return self.fd.read(self.info["sectors_per_cluster"] * self.info["sector_size"])

	# Calculate the logical sector number from the cluster
	def cluster_to_offset(self, cluster):
		offset = ((cluster - 2) * self.info["sectors_per_cluster"]) * self.info["sector_size"]
		return self.__data_start + offset

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
				"size": de[9],
				"direntry": self.fd.tell() - FAT.DIRSIZE
			}

	# Normalizes a 8.3 FAT filename
	def __normalize_name(self, fatname):
		if fatname[8:] == "   ":
			# Skip the dot if there is no file extension
			return fatname[:8].strip(" ")
		else:
			# Otherwise strip the spaces and dotify plus the extension
			return fatname[:8].strip(" ") + "." + fatname[8:].strip(" ")

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
		path = path.lower()
		pos = path.rfind("/")
		items = self.read_dir("" if pos < 0 else path[:pos])
		if items:
			items = filter(lambda x: x["name"].lower() == path[pos+1:], items)
			if items:
				item = items[0]
				data = "".join([self.read_cluster(c) for c in self.get_cluster_chain(item["cluster"])])
				return data[:item["size"]]
		raise FAT.FileNotFoundError(path)

	def write_file(self, path):
		raise NotImplementedError

	def delete_file(self, path):
		# Find the directory entry and replace the first character in the filenames
		# with a 0xe5.  Then get the cluster chain and set all clusters to zero.
		raise NotImplementedError

	# Read all files from a directory
	def read_dir(self, path=""):
		# Start with the root directory
		items = self.__read_dir(self.__root_dir)
		# Filter out empty strings
		subdirs = filter(len, path.lower().split("/"))
		# Now look in all sub directories for our path
		for d in subdirs:
			# Get the one and only directory we are looking for
			items = filter(lambda x: x["attributes"] & FAT.Attribute.DIRECTORY and x["name"].lower() == d, items)
			if not items:
				raise FAT.FileNotFoundError(path)
			items = self.__read_dir(self.cluster_to_offset(items[0]["cluster"]))
		return items

	def set_attribute(self, path, attr):
		slash = path.rfind("/")
		filename = path
		if slash > 0:
			path, filename = path[:slash], path[slash+1:]
		else:
			path = "/"

		for f in self.read_dir(path):
			if filename == f["name"]:
				self.fd.seek(f["direntry"]+11, SEEK_SET)
				self.fd.write(pack("B", attr))
				break
