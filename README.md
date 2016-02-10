# ![RecuperaBit](http://i.imgur.com/Q6mM385.jpg)

A software which attempts to reconstruct file system structures and recover
files. Currently it supports only NTFS.

RecuperaBit attempts reconstruction of the directory structure regardless of:

- missing partition table
- unknown partition boundaries
- partially-overwritten metadata
- quick format

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
such as `/dev/sda` but **this is not advised.**

Optionally, a save file can be specified with `-s`. The first time, after the
scanning process, results are saved in the file. After the first run, the file
is read to only analyze interesting sectors and speed up the loading phase.

Overwriting the save file can be forced with `-w`.

RecuperaBit includes a small command line that allows the user to recover files
and export the contents of a partition in CSV or
[body file](http://wiki.sleuthkit.org/index.php?title=Body_file) format. These
are exported in the directory specified by `-o` (or `recuperabit_output`).

### Pypy

RecuperaBit can be run with the standard cPython implementation, however speed
can be increased by using it with the Pypy interpreter and JIT compiler:

    pypy main.py /path/to/disk.img


## License

This software is released under the GNU GPLv3. See `LICENSE` for more details.
