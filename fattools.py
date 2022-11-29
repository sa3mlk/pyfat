#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from fat import FAT
import sys
import argparse

def get_all_files(fat, path=''):
    files = fat.read_dir(path)
    for f in files:
        if f['name'] == '.' or f['name'] == '..':
            continue
        elif path:
            f['name'] = f'{path}/{f["name"]}'
        if f['attributes'] & FAT.Attribute.DIRECTORY:
            files.extend(get_all_files(fat, f'{path}/{f["name"]}' if path else f['name']))
    return files


def get_file_from_sector(fat, sector):
    files = filter(
        lambda f: ord(f['name'][0]) != 0xe5 and
              f['name'] != '.' and
              f['name'] != '..',
            get_all_files(fat)
    )
    for f in files:
        for c in fat.get_cluster_chain(f['cluster']):
            cluster_sector = fat.cluster_to_offset(c) / fat.info['sector_size']
            if sector >= cluster_sector and sector < (cluster_sector + fat.info['sectors_per_cluster']):
                return f


def get_fragmented_files(fat):
    fragmented_files = []
    for f in get_all_files(fat):
        chain = fat.get_cluster_chain(f['cluster'])
        for i, c in enumerate(chain):
            if len(chain) - 1 == i:
                break
            if c + 1 != chain[i + 1]:
                fragmented_files.append(f)
                break
    return fragmented_files


def parse_args():
    formatter_class=lambda prog: argparse.HelpFormatter(prog, max_help_position=100, width=200)
    parser = argparse.ArgumentParser(formatter_class=formatter_class)
    parser.add_argument('image', help='FAT image')
    parser.add_argument('-l', '--list', metavar='DIR', help='list files in directory')
    parser.add_argument('-f', '--frag', action='store_true', help='list all fragmented files')
    parser.add_argument('-s', '--sect', metavar='SECTOR', help='find out which file is on sector', type=int)
    return parser.parse_args()


def sizeof_fmt(num, suffix='B'):
    for unit in ['', 'Ki', 'Mi', 'Gi', 'Ti', 'Pi', 'Ei', 'Zi']:
        if abs(num) < 1024.0:
            return f'{num:3.1f}{unit}{suffix}'
        num /= 1024.0
    return f'{num:.1f}Yi{suffix}'

def main():
    args = parse_args()

    fat = FAT(open(args.image, 'rb'))

    if args.list:
        for f in get_all_files(fat, '' if args.list == '.' else args.list):
            if f['attributes'] & FAT.Attribute.DIRECTORY:
                print(f'{f["name"]:<30} <DIR>                      {f["last_accessed"]} {f["modified"]}')
            else:
                print(f'{f["name"]:<30} {sizeof_fmt(f["size"]):<10} cluster #{f["cluster"]:<6} {f["last_accessed"]} {f["modified"]}')

    if args.frag:
        for f in get_fragmented_files(fat):
            print(f'{f["name"]} is fragmented')

    if args.sect:
        f = get_file_from_sector(fat, args.sect)
        if f:
            for k, v in f.items():
                print(f'{k+":":<15}{v}')
        else:
            print(f'Cannot find any file that occupies sector {args.sect}')
        
if __name__ == '__main__':
    sys.exit(main())

