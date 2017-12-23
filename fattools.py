#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from fat import FAT
import sys


def get_all_files(fat, path=''):
	files = fat.read_dir(path)
	for f in files:
		if f["name"] == '.' or f["name"] == "..":
			continue
		elif path:
			f["name"] = "%s/%s" % (path, f["name"])
		if f["attributes"] & FAT.Attribute.DIRECTORY:
			files.extend(get_all_files(fat, "%s/%s" % (path, f["name"]) if path else f["name"]))
	return files


def get_file_from_sector(fat, sector):
	files = filter(
		lambda f: ord(f["name"][0]) != 0xe5 and
			  f["name"] != '.' and
			  f["name"] != "..",
			get_all_files(fat)
	)
	for f in files:
		for c in fat.get_cluster_chain(f["cluster"]):
			cluster_sector = fat.cluster_to_offset(c) / fat.info["sector_size"]
			if sector >= cluster_sector and sector < (cluster_sector + fat.info["sectors_per_cluster"]):
				return f


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
	commands = ["--list", "--frag", "--sect"]

	if sys.argv[3:]:
		print("Commands:")
		print('\n'.join(commands))
		print("fattools.py [--command] [argument] [image]")
		sys.exit(1)

	for i, arg in enumerate(argv):
		if arg not in commands:
			continue
		
		print(argv)
		fat = FAT(open(argv[i+2], "rb"))
		if arg == "--list":
			print "List files"
			return True
		elif arg == "--frag":
			fragmented_files = get_fragmented_files(fat)
			for f in fragmented_files:
				print(f["name"], " is fragmented")
			return False
		elif arg == "--sect":
			sector = int(sys.argv[1])
			f = get_file_from_sector(fat, sector)
			if f:
				for k, v in f.iteritems():
					print("%-14.14s%s" % (k, v))
				return False
			print("Cannot find any file that occupies sector", sector)
			return True

		
if __name__ == "__main__":
	sys.exit(main())

