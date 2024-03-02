from errno import *
import fuse
from fuse import Fuse

from stat import S_IFDIR, S_IFLNK, S_IFREG

import os, sys
import logging
from .fs.constants import max_sectors, sector_size
import time
from datetime import datetime
from .fs.core_types import File
import traceback

# was originally named fuse.py until i realized it conflicted with fusepy

def split_all_path(path):
    allpath = []
    while True:
        (head, tail) = os.path.split(path)
        if head == path: # end of absolute path
            allpath.insert(0, head)
            break
        elif tail == path: # end of relative path
            allpath.insert(0, tail)
            break
        else:
            path = head
            allpath.insert(0, tail)
    return allpath

def recurse_path(spath, node):
    if len(spath) == 1:
        return node
    if node.is_directory:
        for entry in node.children:
            if entry.name == spath[1]:
                return recurse_path(spath[1:], entry)
    return None
    
def date2utc(dt):
    if dt is None:
        return time.time()
    return (dt - datetime(1970, 1, 1)).total_seconds()

def _file_view_repr(node):
    """Give the file a name with some metadata about it"""
    desc = ""
    if node.is_ghost:
      desc = desc + '[GHOST]'
    if node.is_deleted:
      desc = desc + '[DELETED]'
    return desc + node.name

class AbstractView(Fuse):
    def __init__(self, *args, **kw):
        Fuse.__init__(self, *args, **kw)
        self.fd = 0
        self.files = {}
        
    def get_part_from_path(self, path):
        raise NotImplementedError
    def get_file_from_path(self, path):
        raise NotImplementedError
    
    def readdir(self, path, offset):
        file = self.get_file_from_path(path)
        
        dirents = ['.', '..']
        if file is not None and file.is_directory:
            for entry in file.children:
                dirents.append(_file_view_repr(entry))
        for r in dirents:
            yield fuse.Direntry(r)

    def getattr(self, path):
        file = self.get_file_from_path(path)
        if file is None:
          return -errno.ENOENT

        attrs = fuse.Stat()
        attrs.st_nlink=1
        attrs.st_blksize=sector_size
        
        if file.is_directory:
            attrs.st_mode = S_IFDIR
        else:
            attrs.st_mode = S_IFREG
            
        if file.size is not None:
            attrs.st_size = file.size
        else:
            attrs.st_size = 0
        
        #TODO grab actual info?
        attrs.st_blocks = (attrs.st_size + (attrs.st_blksize - 1)) // attrs.st_blksize
            
        mac = file.get_mac()
        if mac is not None:
            attrs.st_mtime = date2utc(mac[0])
            attrs.st_atime = date2utc(mac[1])
            attrs.st_ctime = date2utc(mac[2])
        else:
            attrs.st_mtime = time.time()
            attrs.st_atime = time.time()
            attrs.st_ctime = time.time()
        
        return attrs
    
    def open(self, path, mode):
        file = self.get_file_from_path(path)
        if file is None:
            return -errno.ENOENT
        part = self.get_part_from_path(path)
            
        try:
            file.open(part)
        except Exception as e:
            track = traceback.format_exc()
            logging.error(e)
            logging.error(track)
            return -errno.EIO
        
        self.fd += 1
        self.files[self.fd] = file
        return (0, self.fd)
        
    def release(self, path, flags, fh):
        del self.files[fh]
        return 0
    
    def read(self, path, size, offset, fh):
        file = self.get_file_from_path(path)
        part = self.get_part_from_path(path)
        try:
            return file.read(part, offset, size)
        except Exception as e:
            track = traceback.format_exc()
            logging.error(e)
            logging.error(track)
            return -errno.EIO
        
class PartView(AbstractView):
    def __init__(self, part, root, *args, **kw):
        AbstractView.__init__(self, *args, **kw)
        self.part = part
        self.root = root
    
    def get_part_from_path(self, path):
        return self.part
    def get_file_from_path(self, path):
        spath = split_all_path(path)
        return recurse_path(spath, self.root)


class MultiPartView(AbstractView):
    def __init__(self, parts, shorthands, rebuilt, *args, **kw):
        AbstractView.__init__(self, *args, **kw)
        self.partdict = {}
        self.root = File(0, "ROOT", 0, True)
        self.build_tree(parts, shorthands, rebuilt)
        
    def build_tree(self, parts, shorthands, rebuilt):
        for i in range(len(shorthands)):
            i, par = shorthands[i]
            part = parts[par]
            if par not in rebuilt:
                print('Rebuilding partition...')
                part.rebuild()
                rebuilt.add(par)
                print('Done')
            partname = 'Partition ' + str(i)
            file = File(0, partname, 0, True)
            file.set_mac(datetime.now(), datetime.now(), datetime.now())
            
            file.add_child(part.root)
            file.add_child(part.lost)
            self.root.add_child(file)
            
            self.partdict[partname] = part
        self.root.set_mac(datetime.now(), datetime.now(), datetime.now())
        
    
    def get_part_from_path(self, path):
        spath = split_all_path(path)
        return self.partdict[spath[1]]
        
    def get_file_from_path(self, path):
        spath = split_all_path(path)
        # todo include lost files as well?
        return recurse_path(spath, self.root)
