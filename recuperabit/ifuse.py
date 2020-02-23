from errno import *
from fuse import FUSE, FuseOSError, Operations, LoggingMixIn
from stat import S_IFDIR, S_IFLNK, S_IFREG

import os, sys
import logging
from fs.constants import max_sectors, sector_size
import time
from datetime import datetime
from fs.core_types import File

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
        #logging.error("dt is None!")
        return time.time()
    return (dt - datetime(1970, 1, 1)).total_seconds()
    

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

class AbstractView(Operations):
    def __init__(self):
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
        #print(path)
        #print(mac)
        if mac is not None:
            attrs["st_mtime"] = date2utc(mac[0])
            attrs["st_atime"] = date2utc(mac[1])
            attrs["st_ctime"] = date2utc(mac[2])
        else:
            attrs["st_mtime"] = time.time()
            attrs["st_atime"] = time.time()
            attrs["st_ctime"] = time.time()
            #logging.error("No Time!")
        
        return attrs
    
    
    # TODO partial file reads?
    def open(self, path, flags):
        file = self.get_file_from_path(path)
        if file is None:
            raise FuseOSError(ENOENT)
        part = self.get_part_from_path(path)
            
        try:
            content = file.get_content(part)
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
        #print(type(binout))
        
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
        
class PartView(AbstractView):
    def __init__(self, part, root):
        AbstractView.__init__(self)
        self.part = part
        self.root = root
    
    def get_part_from_path(self, path):
        return self.part
    def get_file_from_path(self, path):
        spath = split_all_path(path)
        return recurse_path(spath, self.root)


class MultiPartView(AbstractView):
    def __init__(self, parts, shorthands, rebuilt):
        AbstractView.__init__(self)
        self.partdict = {}
        self.root = File(0, "ROOT", 0, True)
        #self.root.set_mac(datetime.now(), datetime.now(), datetime.now())
        self.build_tree(parts, shorthands, rebuilt)
        
    def build_tree(self, parts, shorthands, rebuilt):
        for i in xrange(len(shorthands)):
            i, par = shorthands[i]
            part = parts[par]
            if par not in rebuilt:
                print 'Rebuilding partition...'
                part.rebuild()
                rebuilt.add(par)
                print 'Done'
            partname = 'Partition ' + str(i)
            file = File(0, partname, 0, True)
            #file.set_mac(datetime.now(), datetime.now(), datetime.now())
            
            file.add_child(part.root)
            file.add_child(part.lost)
            self.root.add_child(file)
            
            self.partdict[partname] = part
        
    
    def get_part_from_path(self, path):
        spath = split_all_path(path)
        return self.partdict[spath[1]]
        
    def get_file_from_path(self, path):
        spath = split_all_path(path)
        # todo include lost files as well?
        return recurse_path(spath, self.root)
