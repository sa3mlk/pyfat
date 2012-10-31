#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from fat import FAT

def get_all_files(fat, path=""):
	files = fat.read_dir(path)
	for f in files:
		if f["name"] == "." or f["name"] == "..":
			continue
		if len(path):
			f["name"] = path + "/" + f["name"]
		if f["attributes"] & FAT.Attribute.DIRECTORY:
			files.extend(get_all_files(fat, path + "/" + f["name"] if len(path) else f["name"]))
	return files

def get_file_from_sector(fat, sector):
	files = filter(
		lambda f:
				ord(f["name"][0]) != 0xe5 and
				f["name"] != "." and
				f["name"] != "..",
			get_all_files(fat)
		)

	for f in files:
		for c in fat.get_cluster_chain(f["cluster"]):
			cluster_sector = fat.cluster_to_offset(c) / fat.info["sector_size"]
			if sector >= cluster_sector and sector < (cluster_sector + fat.info["sectors_per_cluster"]):
				return f

	return None

def get_fragmented_files(fat):
	fragmented_files = []
	for f in get_all_files(fat):
		chain = fat.get_cluster_chain(f["cluster"])
		for i, c in enumerate(chain):
			if len(chain) - 1 == i:
				break
			if c + 1 != chain[i + 1]:
				fragmented_files.append(f)
				break
	return fragmented_files

def main():
	from sys import argv

	commands = ["--list", "--frag", "--sect"]

	if len(argv) != 4:
		print "Commands:"
		print "\n".join(commands)
		print "fattools.py [--command] [argument] [image]"
		exit(1)

	for i, arg in enumerate(argv):
		if arg in commands:
			print argv
			fat = FAT(open(argv[i+2], "rb"))
			if arg == "--list":
				print "List files"
				return 0
			elif arg == "--frag":
				fragmented_files = get_fragmented_files(fat)
				for f in fragmented_files:
					print f["name"], "is fragmented"
				return 0
			elif arg == "--sect":
				sector = int(argv[1])
				f = get_file_from_sector(fat, sector)
				if f:
					for k, v in f.iteritems():
						print "%-14.14s%s" % (k, v)
					return 0
				else:
					print "Cannot find any file that occupies sector", sector
					return 1

if __name__ == "__main__":
	exit(main())

