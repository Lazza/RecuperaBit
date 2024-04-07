#!/usr/bin/env python3
"""Main RecuperaBit process."""

# RecuperaBit
# Copyright 2014-2021 Andrea Lazzarotto
#
# This file is part of RecuperaBit.
#
# RecuperaBit is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# RecuperaBit is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with RecuperaBit. If not, see <http://www.gnu.org/licenses/>.


import argparse
import codecs
import itertools
import locale
import logging
import os.path
import pickle
import re
import shlex
import sys
import subprocess
import sys
import os
from recuperabit import logic, utils
# scanners
from recuperabit.fs.ntfs import NTFSScanner
try:
    import readline
except:
    pass #readline not available

__author__ = "Andrea Lazzarotto"
__copyright__ = "(c) 2014-2021, Andrea Lazzarotto"
__license__ = "GPLv3"
__version__ = "1.1.6"
__maintainer__ = "Andrea Lazzarotto"
__email__ = "andrea.lazzarotto@gmail.com"


# classes of available scanners
plugins = (
    NTFSScanner,
)

commands = (
    ('help', 'Print this help message'),
    ('recoverable', 'List recoverable partitions'),
    ('other', 'List unrecoverable partitions'),
    ('allparts', 'List all partitions'),
    ('tree <part#>', 'Show contents of partition (tree)'),
    ('gtree <part#> <...grep options>', 'Show contents of partition (tree) in a pager, piping through grep. '
                                        'Invalid partition id gets all partitions'),
    ('csv <part#> <path>', 'Save a CSV representation in a file'),
    ('bodyfile <part#> <path>', 'Save a body file representation in a file'),
    ('tikzplot <part#> [<path>]', 'Produce LaTeX code to draw a Tikz figure'),
    ('restore <part#> <file>', 'Recursively restore files from <file>'),
    ('locate <part#> <text>', 'Print all file paths that match a string'),
    ('traceback <part#> <file>', 'Print ids and paths for all ancestors of <file>'),
    ('merge <part#> <part#>', 'Merge the two partitions into the first one'),
    ('quit', 'Close the program')
)

rebuilt = set()


def output_to_pager(text, grep_opts=None):
    try:
        # args for lex stolen from git source, see `man less`
        pager = subprocess.Popen('grep {} | less -F -R -S -X -K'
                                 .format('".*"' if grep_opts is None else grep_opts),
                                 stdin=subprocess.PIPE,
                                 stdout=sys.stdout,
                                 shell=True)
        if text is None:
            pager.stdin.write(bytearray("None", 'utf-8'))
            return
        for line in text:
            pager.stdin.write(bytearray("{}{}".format(line, os.linesep), 'utf-8'))
        pager.stdin.close()
        pager.wait()
    except KeyboardInterrupt:
        pass
        # let less handle this, -K will exit cleanly


def list_parts(parts, shorthands, test):
    """List partitions corresponding to test."""
    for i, part in shorthands:
        if test(parts[part]):
            print('Partition #' + str(i), '->', parts[part])


def get_parts(parts, shorthands, test):
    """List partitions corresponding to test."""
    return [i for i, part in shorthands if test(parts[part])]


def check_valid_part(num, parts, shorthands, rebuild=True):
    """Check if the required partition is valid."""
    try:
        i = int(num)
    except ValueError:
        print('Value is not valid!')
        return None
    if i in range(len(shorthands)):
        i, par = shorthands[i]
        part = parts[par]
        if rebuild and par not in rebuilt:
            print('Rebuilding partition...')
            part.rebuild()
            rebuilt.add(par)
            print('Done')
        return part
    print('No partition with given ID!')
    return None


def quiet_check_valid_part(num, parts, shorthands, rebuild=True):
    """Check if the required partition is valid."""
    # TODO merge this function with the one above: kwarg to remove log
    try:
        i = int(num)
    except ValueError:
        print('Value is not valid!')
        return None
    if i in range(len(shorthands)):
        i, par = shorthands[i]
        part = parts[par]
        if rebuild and par not in rebuilt:
            part.rebuild()
            rebuilt.add(par)
        return part
    print('No partition with given ID!')
    return None


def print_part_tree(part_id, file_filter, parts, shorthands):
    part = check_valid_part(part_id, parts, shorthands)
    if part is not None:
        part_id = int(part_id)
        root = utils.verbose_tree_folder(part_id, part.root, [])
        lost = utils.verbose_tree_folder(part_id, part.lost, [])
        if root:
            output_to_pager(root, file_filter)
        if lost:
            output_to_pager(lost, file_filter)
        print('-' * 10)


def print_all_parts_tree(file_filter, parts, shorthands):
    l_parts = get_parts(parts, shorthands, lambda x: x.recoverable)
    all_parts = filter(lambda p: p is not None, [(i, quiet_check_valid_part(i, parts, shorthands)) for i in l_parts])
    output = []
    for i, part in all_parts:
        root = utils.verbose_tree_folder(i, part.root, [])
        lost = utils.verbose_tree_folder(i, part.lost, [])
        if root:
            output.extend(root)  # TODO: maybe just log to file and not store into memory in case it's too large
        if lost:
            output.extend(lost)  # TODO: maybe no pager if logfile available
        output.extend(['-' * 10])
    #TODO: possibly filter by size as well
    output_to_pager(output, file_filter)


def interpret(cmd, arguments, parts, shorthands, outdir):
    """Perform command required by user."""
    if cmd == 'help':
        print('Available commands:')
        for name, desc in commands:
            print('    %s%s' % (name.ljust(28), desc))
    elif cmd == 'tree':
        if len(arguments) != 1:
            print('Wrong number of parameters!')
        else:
            part = check_valid_part(arguments[0], parts, shorthands)
            if part is not None:
                print('-'*10)
                print(utils.tree_folder(part.root))
                print(utils.tree_folder(part.lost))
                print('-'*10)
    elif cmd == 'gtree':
        if len(arguments) < 2:
            file_filter = '".*"'
        else:
            file_filter = '"' + '" "'.join(arguments[1:]) + '"'
        part = quiet_check_valid_part(arguments[0], parts, shorthands)
        if part is not None:
            print_part_tree(arguments[0], file_filter, parts, shorthands)
        else:
            print_all_parts_tree(file_filter, parts, shorthands)
    elif cmd == 'bodyfile':
        if len(arguments) != 2:
            print('Wrong number of parameters!')
        else:
            part = check_valid_part(arguments[0], parts, shorthands)
            if part is not None:
                contents = [
                    '# ---' + repr(part) + '---',
                    '# Full paths'
                ] + utils.bodyfile_folder(part.root) + [
                    '# \n# Orphaned files'
                ] + utils.bodyfile_folder(part.lost)
                fname = os.path.join(outdir, arguments[1])
                try:
                    with codecs.open(fname, 'w', encoding='utf8') as outfile:
                        outfile.write('\n'.join(contents))
                        print('Saved body file to %s' % fname)
                except IOError:
                    print('Cannot open file %s for output!' % fname)
    elif cmd == 'csv':
        if len(arguments) != 2:
            print('Wrong number of parameters!')
        else:
            part = check_valid_part(arguments[0], parts, shorthands)
            if part is not None:
                contents = utils.csv_part(part)
                fname = os.path.join(outdir, arguments[1])
                try:
                    with codecs.open(fname, 'w', encoding='utf8') as outfile:
                        outfile.write(
                            '\n'.join(contents)
                        )
                        print('Saved CSV file to %s' % fname)
                except IOError:
                    print('Cannot open file %s for output!' % fname)
    elif cmd == 'tikzplot':
        if len(arguments) not in (1, 2):
            print('Wrong number of parameters!')
        else:
            part = check_valid_part(arguments[0], parts, shorthands)
            if part is not None:
                if len(arguments) > 1:
                    fname = os.path.join(outdir, arguments[1])
                    try:
                        with codecs.open(fname, 'w') as outfile:
                            outfile.write(utils.tikz_part(part) + '\n')
                            print('Saved Tikz code to %s' % fname)
                    except IOError:
                        print('Cannot open file %s for output!' % fname)
                else:
                    print(utils.tikz_part(part))
    elif cmd == 'restore':
        if len(arguments) != 2:
            print('Wrong number of parameters!')
        else:
            partid = arguments[0]
            part = check_valid_part(partid, parts, shorthands)
            if part is not None:
                index = arguments[1]
                partition_dir = os.path.join(outdir, 'Partition' + str(partid))
                myfile = None
                try:
                    indexi = int(index)
                except ValueError:
                    indexi = index
                for i in [index, indexi]:
                    myfile = part.get(i, myfile)
                if myfile is None:
                    print('The index is not valid')
                else:
                    logic.recursive_restore(myfile, part, partition_dir)
    elif cmd == 'locate':
        if len(arguments) != 2:
            print('Wrong number of parameters!')
        else:
            part = check_valid_part(arguments[0], parts, shorthands)
            if part is not None:
                text = arguments[1]
                results = utils.locate(part, text)
                for node, path in results:
                    desc = (
                        ' [GHOST]' if node.is_ghost else
                        ' [DELETED]' if node.is_deleted else ''
                    )
                    print('[%s]: %s%s' % (node.index, path, desc))
    elif cmd == 'traceback':
        if len(arguments) != 2:
            print('Wrong number of parameters!')
        else:
            partid = arguments[0]
            part = check_valid_part(partid, parts, shorthands)
            if part is not None:
                index = arguments[1]
                myfile = None
                try:
                    indexi = int(index)
                except ValueError:
                    indexi = index
                for i in [index, indexi]:
                    myfile = part.get(i, myfile)
                if myfile is None:
                    print('The index is not valid')
                else:
                    while myfile is not None:
                        print('[{}] {}'.format(myfile.index, myfile.full_path(part)))
                        myfile = part.get(myfile.parent)
    elif cmd == 'merge':
        if len(arguments) != 2:
            print('Wrong number of parameters!')
        else:
            part1 = check_valid_part(arguments[0], parts, shorthands, rebuild=False)
            part2 = check_valid_part(arguments[1], parts, shorthands, rebuild=False)
            if None in (part1, part2):
                return
            if part1.fs_type != part2.fs_type:
                print('Cannot merge partitions with types (%s, %s)' % (part1.fs_type, part2.fs_type))
                return
            print('Merging partitions...')
            utils.merge(part1, part2)
            source_position = int(arguments[1])
            destination_position = int(arguments[0])
            _, par_source = shorthands[source_position]
            _, par_destination = shorthands[destination_position]
            del shorthands[source_position]
            del parts[par_source]
            for par in (par_source, par_destination):
                try:
                    rebuilt.remove(par)
                except:
                    pass
            print('There are now %d partitions.' % (len(parts), ))
    elif cmd == 'recoverable':
        list_parts(parts, shorthands, lambda x: x.recoverable)
    elif cmd == 'other':
        list_parts(parts, shorthands, lambda x: not x.recoverable)
    elif cmd == 'allparts':
        list_parts(parts, shorthands, lambda x: True)
    elif cmd == 'quit':
        exit(0)
    else:
        print('Unknown command.')


def main():
    """Wrap the program logic inside a function."""
    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

    print("     ___                                ___ _ _   ")
    print("    | _ \___ __ _  _ _ __  ___ _ _ __ _| _ |_) |_ ")
    print("    |   / -_) _| || | '_ \/ -_) '_/ _` | _ \ |  _|")
    print("    |_|_\___\__|\_,_| .__/\___|_| \__,_|___/_|\__|")
    print("                    |_|   v{}".format(__version__))
    print('   ', __copyright__, '<%s>' % __email__)
    print('    Released under the', __license__)
    print('')

    parser = argparse.ArgumentParser(
        description='Reconstruct the directory structure of possibly damaged '
                    'filesystems.'
    )
    parser.add_argument('path', type=str, help='path to the disk image')
    parser.add_argument(
        '-s', '--savefile', type=str, help='path of the scan save file'
    )
    parser.add_argument(
        '-w', '--overwrite', action='store_true',
        help='force overwrite of the save file'
    )
    parser.add_argument(
        '-o', '--outputdir', type=str, help='directory for restored contents'
        ' and output files'
    )
    parser.add_argument(
        '-l', '--outputlog', type=str, help='file for logs to be stored'
    )
    parser.add_argument(
        '-n', '--skipexisting', type=str, help='do not write anew content for existing files to output dir'
    )
    args = parser.parse_args()

    try:
        image = open(args.path, 'rb')
    except IOError:
        logging.error('Unable to open image file!')
        exit(1)

    read_results = False
    write_results = False

    # Set output directory
    if args.outputdir is None:
        logging.info('No output directory specified, defaulting to '
                     'recuperabit_output')
        args.outputdir = 'recuperabit_output'

    if args.outputlog is None:
        logging.info('No output directory specified, defaulting to '
                     'recuperabit_output/restore.log')
        # TODO: write output from gtree to file

    if args.skipexisting is None:
        logic.__skip_existing_files__ = True
        logging.info('No skip existing specified, defaulting to True')
    else:
        logic.__skip_existing_files__ = args.skipexisting != "False"

    # Try to reload information from the savefile
    if args.savefile is not None:
        if args.overwrite:
            logging.info('Results will be saved to %s', args.savefile)
            write_results = True
        else:
            logging.info('Checking if results already exist.')
            try:
                savefile = open(args.savefile, 'rb')
                logging.info('Results will be read from %s', args.savefile)
                read_results = True
            except IOError:
                logging.info('Unable to open save file.')
                logging.info('Results will be saved to %s', args.savefile)
                write_results = True

    if read_results:
        logging.info('The save file exists. Trying to read it...')
        try:
            indexes = pickle.load(savefile)
            savefile.close()
        except IndexError:
            logging.error('Malformed save file!')
            exit(1)
    else:
        indexes = itertools.count()

    # Ask for confirmation before beginning the process
    try:
        confirm = input('Type [Enter] to start the analysis or '
                        '"exit" / "quit" / "q" to quit: ')
    except EOFError:
        print('')
        exit(0)
    if confirm in ('exit', 'quit', 'q'):
        exit(0)

    # Create the output directory
    if not logic.makedirs(args.outputdir):
        logging.error('Cannot create output directory!')
        exit(1)

    scanners = [pl(image) for pl in plugins]

    logging.info('Analysis started! This is going to take time...')
    interesting = utils.feed_all(image, scanners, indexes)

    logging.info('First scan completed')

    if write_results:
        logging.info('Saving results to %s', args.savefile)
        with open(args.savefile, 'wb') as savefile:
            pickle.dump(interesting, savefile)

    # Ask for partitions
    parts = {}
    for scanner in scanners:
        parts.update(scanner.get_partitions())

    shorthands = list(enumerate(parts))

    logging.info('%i partitions found.', len(parts))
    while True:
        print('\nWrite command ("help" for details):')
        try:
            command = shlex.split(input('> '))
        except (EOFError, KeyboardInterrupt):
            print('')
            exit(0)
        try:
            cmd = command[0]
            arguments = command[1:]
        except IndexError:
            continue
        interpret(cmd, arguments, parts, shorthands, args.outputdir)

if __name__ == '__main__':
    main()
