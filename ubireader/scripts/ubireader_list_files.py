#!/usr/bin/env python

#############################################################
# ubi_reader
# (C) Collin Mulliner based on Jason Pruitt's ubireader_extract_images
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#############################################################

import os
import sys
import time
import argparse

from ubireader import settings
from ubireader.ubi import ubi
from ubireader.ubi.defines import UBI_EC_HDR_MAGIC
from ubireader.ubifs import ubifs
from ubireader.ubifs.list import list_files, copy_file
from ubireader.ubifs.defines import UBIFS_NODE_MAGIC
from ubireader.ubi_io import ubi_file, leb_virtual_file
from ubireader.debug import error, log
from ubireader.utils import guess_filetype, guess_start_offset, guess_leb_size, guess_peb_size

def main():
    start = time.time()
    description = 'List and Extract files of a UBI or UBIFS image.'
    usage = 'ubireader_list_files [options] filepath'
    parser = argparse.ArgumentParser(usage=usage, description=description)

    parser.add_argument('-l', '--log', action='store_true', dest='log',
                      help='Print extraction information to screen.')

    parser.add_argument('-v', '--verbose-log', action='store_true', dest='verbose',
                      help='Prints nearly everything about anything to screen.')
    
    parser.add_argument('-p', '--peb-size', type=int, dest='block_size',
                        help='Specify PEB size. (UBI Only)')
    
    parser.add_argument('-e', '--leb-size', type=int, dest='block_size',
                        help='Specify LEB size. (UBIFS Only)')

    parser.add_argument('-s', '--start-offset', type=int, dest='start_offset',
                        help='Specify offset of UBI/UBIFS data in file. (default: 0)')

    parser.add_argument('-n', '--end-offset', type=int, dest='end_offset',
                        help='Specify end offset of UBI/UBIFS data in file.')

    parser.add_argument('-g', '--guess-offset', type=int, dest='guess_offset',
                        help='Specify offset to start guessing where UBI data is in file. (default: 0)')

    parser.add_argument('-w', '--warn-only-block-read-errors', action='store_true', dest='warn_only_block_read_errors',
                      help='Attempts to continue extracting files even with bad block reads. Some data will be missing or corrupted! (default: False)')

    parser.add_argument('-i', '--ignore-block-header-errors', action='store_true', dest='ignore_block_header_errors',
                      help='Forces unused and error containing blocks to be included and also displayed with log/verbose. (default: False)')

    parser.add_argument('-f', '--u-boot-fix', action='store_true', dest='uboot_fix',
                      help='Assume blocks with image_seq 0 are because of older U-boot implementations and include them. (default: False)')

    parser.add_argument('-P', '--path', dest='listpath',
                        help='Path to list.')

    parser.add_argument('-C', '--copy', dest='copyfile',
                        help='File to Copy.')

    parser.add_argument('-D', '--copy-dest', dest='copyfiledest',
                        help='Copy Destination.')

    parser.add_argument('-K', '--master-key', dest='master_key',
                      help='Master key file, given with fscryptctl e.g. to encrypt the UBIFS (support limited to fscrypt v1 policies)')

    parser.add_argument('filepath', help='UBI/UBIFS image file.')

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()

    settings.logging_on = args.log

    settings.logging_on_verbose = args.verbose

    settings.warn_only_block_read_errors = args.warn_only_block_read_errors

    settings.ignore_block_header_errors = args.ignore_block_header_errors

    settings.uboot_fix = args.uboot_fix

    if args.master_key:
        path = args.master_key
        if not os.path.exists(path):
            parser.error("File path doesn't exist.")
        else :
            with open(path, "rb") as file:
                if os.stat(path).st_size != 64:
                    parser.error("Master key file size is not 64 bytes.")
                else:
                    master_key = file.read(64)
    else:
        master_key = None

    if args.filepath:
        path = args.filepath
        if not os.path.exists(path):
            parser.error("File path doesn't exist.")

    if args.start_offset:
        start_offset = args.start_offset
    elif args.guess_offset:
        start_offset = guess_start_offset(path, args.guess_offset)
    else:
        start_offset = guess_start_offset(path)

    if args.end_offset:
        end_offset = args.end_offset
    else:
        end_offset = None

    filetype = guess_filetype(path, start_offset)
    if not filetype:
        parser.error('Could not determine file type.')

    if args.block_size:
        block_size = args.block_size
    else:
        if filetype == UBI_EC_HDR_MAGIC:
            block_size = guess_peb_size(path)
        elif filetype == UBIFS_NODE_MAGIC:
            block_size = guess_leb_size(path)

        if not block_size:
            parser.error('Block size could not be determined.')

    # Create file object.
    ufile_obj = ubi_file(path, block_size, start_offset, end_offset)

    if filetype == UBI_EC_HDR_MAGIC:
        # Create UBI object
        ubi_obj = ubi(ufile_obj)

        # Loop through found images in file.
        for image in ubi_obj.images:

            # Loop through volumes in each image.
            for volume in image.volumes:

                # Get blocks associated with this volume.
                vol_blocks = image.volumes[volume].get_blocks(ubi_obj.blocks)

                # Skip volume if empty.
                if not len(vol_blocks):
                    continue

                # Create LEB backed virtual file with volume blocks.
                # Necessary to prevent having to load entire UBI image
                # into memory.
                lebv_file = leb_virtual_file(ubi_obj, vol_blocks)

                # Create UBIFS object.
                ubifs_obj = ubifs(lebv_file, master_key=master_key)

                if args.listpath:
                    list_files(ubifs_obj, args.listpath)
                if args.copyfile and args.copyfiledest:
                    copy_file(ubifs_obj, args.copyfile, args.copyfiledest)

    elif filetype == UBIFS_NODE_MAGIC:
        # Create UBIFS object
        ubifs_obj = ubifs(ufile_obj, master_key=master_key)

        if args.listpath:
            list_files(ubifs_obj, args.listpath)
        if args.copyfile and args.copyfiledest:
            copy_file(ubifs_obj, args.copyfile, args.copyfiledest)

    else:
        print('Something went wrong to get here.')

    ufile_obj.close()


if __name__=='__main__':
    main()
