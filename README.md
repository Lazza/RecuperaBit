

# ![RecuperaBit](http://i.imgur.com/Q6mM385.jpg)

[![Support via PayPal](https://cdn.rawgit.com/twolfson/paypal-github-button/1.0.0/dist/button.svg)](https://www.paypal.me/AndreaLazzarotto/)

A software which attempts to reconstruct file system structures and recover
files. Currently it supports only NTFS.

RecuperaBit attempts reconstruction of the directory structure regardless of:

- missing partition table
- unknown partition boundaries
- partially-overwritten metadata
- quick format

You can get more information about **the reconstruction algorithms** and the
architecture used in RecuperaBit by reading
[my MSc thesis](https://www.scribd.com/doc/309337813/) or checking out [the
slides](http://www.slideshare.net/TheLazza/recuperabit-forensic-file-system-reconstruction-given-partially-corrupted-metadata).

## Usage

    usage: main.py [-h] [-s SAVEFILE] [-w] [-o OUTPUTDIR] path

    Reconstruct the directory structure of possibly damaged filesystems.

    positional arguments:
      path                  path to the disk image

    optional arguments:
      -h, --help            show this help message and exit
      -s SAVEFILE, --savefile SAVEFILE
                            path of the scan save file
      -w, --overwrite       force overwrite of the save file
      -o OUTPUTDIR, --outputdir OUTPUTDIR
                            directory for restored contents and output files

The main argument is the `path` to a bitstream image of a disk or partition.
RecuperaBit automatically determines the sectors from which partitions start.

RecuperaBit does not modify the disk image, however it does read some parts of
it multiple times through the execution. It should also work on real devices,
such as `/dev/sda` but **this is not advised** for damaged drives. RecuperaBit
might worsen the situation by "stressing" a damaged drive or it could crash due
to an I/O error.

Optionally, a save file can be specified with `-s`. The first time, after the
scanning process, results are saved in the file. After the first run, the file
is read to only analyze interesting sectors and speed up the loading phase.

Overwriting the save file can be forced with `-w`.

RecuperaBit includes a small command line that allows the user to recover files
and export the contents of a partition in CSV or
[body file](http://wiki.sleuthkit.org/index.php?title=Body_file) format. These
are exported in the directory specified by `-o` (or `recuperabit_output`).

### Limitation

Currently RecuperaBit does not work with compressed files on an NTFS filesystem. If you have deep knowledge of the inner workings of file compression on NTFS filesystem, your help would be much appreciated, as available documentation is quite sparse on the topic.

### Pypy

RecuperaBit can be run with the standard cPython implementation, however speed
can be increased by using it with the Pypy interpreter and JIT compiler:

    pypy main.py /path/to/disk.img

### Docker
The container is built on top of debian:buster and pypy 

Before you start pull the newest version

    docker pull h4r0/recuperabit

To automatically destroy the container after use run it with --rm

    docker run -it --rm h4r0/recuperabit --help

Example for a drive image copy created with dd/ddrescue etc. (recommended)
Adjust the paths "*/path/to/*" to your needs

    docker run -it --rm \
    -v "/path/to/drive.img:/drive.img" \
    -v "/path/to/outputdir/:/output" \
    -v "/path/to/save.log:/save.log" \
    h4r0/recuperabit

The arguments "-s, -o" and "path" are passed by default, if you want to run custom args specifiy them after "*h4r0/recuperabit*"

    docker run -it --rm \
    -v "/path/to/drive.img:/drive.img" \
    -v "/path/to/outputdir/:/output" \
    -v "/path/to/save.log:/save.log" \
    h4r0/recuperabit -w -o /output /drive.img

Working directly with raw devices for example /dev/sda

    docker run -it --rm \
    --device /dev/sda \
    -v "/path/to/outputdir/:/output" \
    -v "/path/to/save.log:/save.log" \ 
    h4r0/recuperabit -s /save.log -o /output /dev/sda


### Recovery of File Contents

Files can be restored one at a time or recursively, starting from a directory.
After the scanning process has completed, you can check the list of partitions
that can be recovered by issuing the following command at the prompt:

    recoverable

Each line shows information about a partition. Let's consider the following
output example:

    Partition #0 -> Partition (NTFS, 15.00 MB, 11 files, Recoverable, Offset: 2048, Offset (b): 1048576, Sec/Clus: 8, MFT offset: 2080, MFT mirror offset: 17400)

If you want to recover files starting from a specific directory, you can either
print the tree on screen with the `tree` command (very verbose for large drives)
or you can export a CSV list of files (see `help` for details).

If you rather want to extract all files from the *Root* and the *Lost Files*
nodes, you need to know the identifier for the root directory, depending on
the file system type. The following are those of file systems supported by
RecuperaBit:

| File System Type | Root Id |
|------------------|---------|
| NTFS             | 5       |

The id for *Lost Files* is -1 **for every file system.**

Therefore, to restore `Partition #0` in our example, you need to run:

    restore 0 5
    restore 0 -1

The files will be saved inside the output directory specified by `-o`.

## License

This software is released under the GNU GPLv3. See `LICENSE` for more details.
