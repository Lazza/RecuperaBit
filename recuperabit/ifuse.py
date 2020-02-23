from errno import *
from fuse import FUSE, FuseOSError, Operations, LoggingMixIn

import os, sys

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
