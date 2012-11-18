#!/usr/bin/python

import re
import sys
from optparse import OptionParser
from pprint import pprint

def register(cls):
    super(cls,cls).register(cls)

class kconfigline(object):
    """
    Object representing a line in a config file
    """
    registry = []
    indexhash = {}

    @classmethod
    def mycmp(cls,a,b):
        return b.prio - a.prio

    @classmethod
    def register(cls, subcls):
        cls.registry.append(subcls)
        cls.registry.sort(cmp=cls.mycmp)

    def __init__(self,fname="<unknown>"):
        self.override_message = None
        self.fname = fname

    @classmethod
    def newline(mycls,line,fname="<unknown>",indexname=None):
        """Main constructor:  given a line, return an object of
        the appropriate type"""
        # figure out which class the line belongs to
        for cls in mycls.registry:
            if cls.regex.match(line):
                subcls = cls
                break
        obj = subcls(line,fname)
        obj.index(indexname)
        return obj
        
    def convert(self,converted):
        oldvals = converted.__dict__
        converted.__dict__ = self.__dict__
        converted.__class__ = self.__class__
        converted.override_message = oldvals['override_message']
        converted.fname = oldvals['fname']

    def index(self,indexname):
        if indexname is None:
            indexname = self.fname
        if not self.indexhash.has_key(indexname):
            self.indexhash[indexname] = {}
        if self.indexhash[indexname].has_key(self.name):
            # override existing value
            # this is done as an object switcheroo so that
            # we don't have to maintain the order of the kconfig
            # class's list of kconfigline objects
            overridden = self.indexhash[indexname][self.name]
            fname = overridden.fname
            if options.verbosity >= 4:
                sys.stderr.write(("    overriding %s:\n        base file %s\n"
                                  "        override file %s\n") % \
                                     (self.name,fname,self.fname))
            # set a note to be printed
            msg = "# overridden from %s; was %s" % \
                (self.fname,overridden.override_text())
            if overridden.override_message:
                msg = overridden.override_message + "\n" + msg
            overridden.override_message = msg
            # convert object into clone of self
            self.convert(overridden)
            # convert self into comment
            c = kconfigline.newline("# (in file %s, overrode %s: %s)" %
                                    (fname,self.name,
                                     overridden.override_text()))
            c.convert(self)
        else:
            self.indexhash[indexname][self.name] = self

    def overridestr(self):
        if self.override_message:
            return self.override_message + "\n"
        else:
            return ""

    def isacomment(self):
        return False

@register
class kconfigcomment(kconfigline):
    prio = 5
    regex = re.compile(r".*")

    def __init__(self,line,fname="<unknown>"):
        kconfigline.__init__(self,fname)
        self.line = line
    
    def index(self,indexname):
        pass

    def __str__(self):
        return self.line

    def isacomment(self):
        return True

@register
class kconfigsetitem(kconfigline):
    """Class representing lines like 'CONFIG_FOO=m'"""
    regex = re.compile(r'^(CONFIG_[\w]+)=("?[^"]*"?)$')
    prio = 10

    def __init__(self,line,fname="<unknown>"):
        kconfigline.__init__(self,fname)
        match = self.regex.match(line)
        self.name = match.group(1)
        self.value = match.group(2)

    def __str__(self):
        return "%s%s=%s" % (self.overridestr(), self.name, self.value)

    def override_text(self):
        return "=%s" % (self.value)

@register
class kconfigunsetitem(kconfigline):
    """Class representing lines like '# CONFIG_FOO is not set'"""
    regex = re.compile(r"^\# ([\w]+) is not set$")
    prio = 10

    def __init__(self,line,fname="<unknown>"):
        kconfigline.__init__(self,fname)
        match = self.regex.match(line)
        self.name = match.group(1)
        self.value = 'not set'

    def __str__(self):
        return "%s# %s is not set" % (self.overridestr(), self.name)

    def override_text(self):
        return "not set"


class kconfig(object):
    """
    Object representing a kernel configuration
    """
    def __init__(self):
        self.lines = []
        self.fnames = []

    @classmethod
    def readfile(mycls,options,fname,index=None,merge=None):
        """
        Read a file from fname
        If variant is defined, look for a variant file to merge
        """
        if index is None:
            index=fname
        if merge is None:
            obj = mycls()
            obj.fname = fname
            obj.arch = options.arch
        else:
            obj = merge
        if (options.verbosity >= 3):
            sys.stderr.write("reading file %s\n" % fname)
        try:
            f = open(fname,'r')
        except Exception, e:
            sys.stderr.write ("Failed to open file %s:  %s\n" %
                              (fname, str(e)))
            exit (1)

        obj.lines.append(
            kconfigline.newline("#\n#\n# Beginning of file %s\n#" % fname))
        for line in f:
            if options.verbosity >= 9:
                sys.stderr.write(line)
            line = line.rstrip()
            obj.lines.append(kconfigline.newline(line,fname,index))
        obj.lines.append(
            kconfigline.newline("#\n# End of file %s\n#" % fname))
        if options.verbosity >= 4:
            sys.stderr.write("Read file with about %d lines\n" % len(obj.lines))
        f.close()

        # Look for the variant file and merge it
        if options.variant is not None:
            try:
                variantfile=fname + options.variant
                # if this causes an exception, it wasn't meant to be
                open(variantfile,'r')
                sys.stderr.write("found variantfile %s\n  ..." % \
                                     variantfile)
                obj = obj.merge(options,variantfile)
            except IOError:
                pass
        return obj


    def merge(self,options,*fname_tup):
        fnames = []
        fnames.extend(fname_tup)

        while fnames:
            if (options.verbosity >= 2):
                sys.stderr.write("merging %s\n  ..." % fnames[-1])
            self = kconfig.readfile(options,fnames.pop(),'merge',self)

        return self


    def hash(self):
        return dict((l.name,l) for l in self.lines if hasattr(l,'name'))
        

    def diff(self,kc2):
        """
        Print the difference between two config files
        """
        hash1 = self.hash()
        hash2 = kc2.hash()
        keys1 = sorted(hash1.keys())
        keys2 = sorted(hash2.keys())

        format = "%-40s %-15s %-15s"

        sys.stderr.write ("file1:  %s\nfile2:  %s\n" % (self.fname,kc2.fname))
        sys.stderr.write ((format % ('','file1','file2'))+'\n')

        while (keys1 or keys2):
            if len(keys1) == 0:
                # done with file1
                key = keys2.pop(0)
                val1 = '--'
                val2 = hash2[key].value
            elif len(keys2) == 0:
                # done with file2
                key = keys1.pop(0)
                val1 = hash1[key].value
                val2 = '--'
            elif cmp(keys1[0],keys2[0]) == -1:
                # option only in file1
                key = keys1.pop(0)
                val1 = hash1[key].value
                val2 = '--'
            elif cmp(keys1[0],keys2[0]) == 1:
                # option only in file2
                key = keys2.pop(0)
                val1 = '--'
                val2 = hash2[key].value
            else:
                # both files have the key
                key = keys1.pop(0)
                keys2.pop(0)
                if cmp(hash1[key].value,hash2[key].value) == 0:
                    # value is the same in both files
                    continue
                # otherwise, value is different
                val1 = hash1[key].value
                val2 = hash2[key].value
            if len(val1) <= 15:
                print(format % (key, val1, val2))
            else:
                print(format % (key, val1, ''))
                print(format % ('', '', val2))

    def write(self,options):
        if options.output:
            if options.verbosity >=2:
                sys.stderr.write("Writing to %s\n" % options.output)
            f = open(options.output,'w')
            f.write(self.tostring(options))
            f.close()
        else:
            print self.tostring(options)

    def tostring(self,options=None):
        if options is None:
            no_comments = False
        else:
            no_comments = options.no_comments
        if options.verbosity >=3:
            sys.stderr.write("no_comments = %s\n" % str(no_comments))

        if self.arch and not no_comments:
            archstr = '# %s\n' % self.arch
        else:
            archstr = ''

        lines = []
        for l in self.lines:
            if not (no_comments and l.isacomment()):
                lines.append(str(l))
        return archstr + "\n".join(lines)

    def __str__(self):
        return self.tostring()


if __name__ == "__main__":
    parser = OptionParser()
    parser.add_option("-d", "--diff", dest="diff", action="store_true",
                      default=False,
                      help="Show differences between two files")
    parser.add_option("-p", "--print", dest="printer", action="store_true",
                      default=False,
                      help="Process and print file")
    parser.add_option("-m", "--merge", dest="merge", action="store_true",
                      default=False,
                      help="Merge two files")
    parser.add_option("-v", "--variant", dest="variant", action="store",
                      default=None,
                      help="Merge any variant files")
    parser.add_option("-a", "--arch", dest="arch", action="store",
                      default=None,
                      help="Arch name to put at top of file")
    parser.add_option("-o", "--output", dest="output", action="store",
                      default=None,
                      help="Output file; default stdout")
    parser.add_option("--verbosity", dest="verbosity", action="store",
                      type="int", default=0,
                      help="Verbosity level 0..10")
    parser.add_option("--no-comments", dest="no_comments", action="store_true",
                      default=False,
                      help="Do not include comments in output")

    (options, args) = parser.parse_args()

    if options.diff:
        if len(args) < 2:
            sys.stderr.write("diff mode requires at least two files\n")
            exit (1)
        kc1 = kconfig.readfile(options,args[0])
        kc2 = kconfig.readfile(options,args[1])
        kc1.diff(kc2)
    elif options.printer:
        if len(args) != 1:
            sys.stderr.write ("print mode requires exactly one file\n")
            exit (1)
        kc = kconfig.readfile(options,args[0])
        kc.write(options)
    elif options.merge:
        if len(args) < 2:
            sys.stderr.write ("merge mode requires at least two files\n")
            exit (1)
        if options.verbosity > 0:
            sys.stderr.write ("merging files %s\n" % (', '.join(args)))

        if (options.verbosity >= 2):
            sys.stderr.write("reading base file %s\n  ..." % args[-1])
        m = kconfig.readfile(options,args.pop(),'merge').merge(options,*args)
        m.write(options)

    exit (0)

