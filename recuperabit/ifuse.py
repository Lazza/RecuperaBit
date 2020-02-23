from errno import *
from fuse import FUSE, FuseOSError, Operations, LoggingMixIn
from stat import S_IFDIR, S_IFLNK, S_IFREG

import os, sys
import logging
from fs.constants import max_sectors, sector_size
import time
import datetime

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
    return (dt - datetime.datetime(1970, 1, 1)).total_seconds()
    

# TODO make this more fitting....
def _file_view_repr(node):
    """Give the file a name with some metadata about it"""
    """desc = (
        '[GHOST]' if node.is_ghost else
        '[DELETED]' if node.is_deleted else ''
    )

    #tail = '/' if node.is_directory else ''
    tail = ''
    data = [
        ('Id', node.index),
        ('Offset', node.offset),
        (
            'Offset bytes',
            node.offset * sector_size
            if node.offset is not None else None
        )
        # ('MAC', node.mac)
    ]
    if not node.is_directory:
        data += [('Size', readable_bytes(node.size))]
    return u'%s%s (%s) %s' % (
        node.name, tail, ', '.join(a + ': ' + str(b) for a, b in data), desc
    )"""
    return node.name

class PartView(Operations):
    def __init__(self, part):
        self.part = part
        self.fd = 0
        self.files = {}
                
    def get_file_from_path(self, path):
        spath = split_all_path(path)
        # todo include lost files as well
        return recurse_path(spath, self.part.root)
    
    def readdir(self, path, offset):
        file = self.get_file_from_path(path)
        
        dirents = ['.', '..']
        if file is not None and file.is_directory:
            for entry in file.children:
                dirents.append(_file_view_repr(entry))
        for r in dirents:
            yield r

    def getattr(self, path, fh=None):
        file = self.get_file_from_path(path)
        if file is None:
            raise FuseOSError(ENOENT)

        attrs = dict(
            st_nlink=1,
            st_blksize=sector_size
            )
        
        if file.is_directory:
            attrs["st_mode"] = S_IFDIR
        else:
            attrs["st_mode"] = S_IFREG
            
        if file.size is not None:
            attrs["st_size"] = file.size
        else:
            #print("unknown size")
            attrs["st_size"] = 0
        
        #TODO grab actual info?
        attrs["st_blocks"] = (attrs["st_size"] + (attrs["st_blksize"] - 1)) // attrs["st_blksize"]
            
        mac = file.get_mac()
        if mac is not None:
            attrs["st_mtime"] = date2utc(mac[0])
            attrs["st_atime"] = date2utc(mac[1])
            attrs["st_ctime"] = date2utc(mac[2])
        else:
            attrs["st_mtime"] = time.time()
            attrs["st_atime"] = time.time()
            attrs["st_ctime"] = time.time()
        
        return attrs
    
    
    # TODO partial file reads?
    def open(self, path, flags):
        file = self.get_file_from_path(path)
        if file is None:
            raise FuseOSError(ENOENT)
            
        try:
            content = file.get_content(self.part)
        except NotImplementedError:
            logging.error(u'Restore of #%s is not supported', file.index)
            raise FuseOSError(EIO)
        
        
        if file.is_directory and content is not None:
            logging.warning(u'Directory %s has data content!', file.file_path)

        binarray = bytearray()
        if content is not None:
            logging.info(u'Restoring #%s %s', file.index, path)
            if hasattr(content, '__iter__'):
                for piece in content:
                    binarray.extend(piece)
            else:
                binarray.extend(content)
        """else:
            if not is_directory:
                # Empty file
                pass
            else:
                raise FuseOSError(EIO)"""

        binout = bytes(binarray)
        print(type(binout))
        
        self.fd += 1
        self.files[self.fd] = (file, binout)
        return self.fd
        
    def release(self, path, fh):
        self.files[fh] = None
        return 0
    
    def read(self, path, size, offset, fh):
        content = self.files[fh][1]
        if content is None:
            raise FuseOSError(EIO)
        return content[offset:offset+size]
