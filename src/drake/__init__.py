import copy, os, hashlib, platform, re, sys, time

def clone(o):

    return copy.deepcopy(o)


class Exception(Exception):

    pass


DEBUG = 'DRAKE_DEBUG' in os.environ

def debug(msg):

    global DEBUG
    if DEBUG:
        print >> sys.stderr, msg

class Path:

    def __init__(self, path):

        self.absolute = False
        if path.__class__ == list:
            self.path = path
        elif path.__class__ == Path:
            self.path = clone(path.path)
            self.absolute = path.absolute
        else:
            assert path
            if platform.system() == 'Windows':
                self.path = re.split(r'/|\\', path)
                self.absolute = bool(self.path[0] == '' or re.compile('^[A-Z]:').match(self.path[0]))
            else:
                self.path = path.split('/')
                self.absolute = self.path[0] == ''

    def __getattr__(self, name):

        if name == 'extension':
            parts = self.path[-1].split('.')
            if len(parts) > 1:
                return parts[-1]
            else:
                return ''
        return object.__getattr__(self, name)

    def __setattr__(self, name, value):

        if name == 'extension':
            parts = self.path[-1].split('.')
            if len(parts) > 1:
                if value == '':
                    parts.pop()
                else:
                    parts[-1] = value
                self.path[-1] = '.'.join(parts)
            else:
                if value != '':
                    self.path[-1] += '.%s' % value
        else:
            self.__dict__[name] = value
        return value

    def __str__(self):

        return '/'.join(self.path)

    def __repr__(self):

        return 'Path(\"%s\")' % str(self)

    def __lt__(self, rhs):

        return str(self) < str(rhs)

    def __hash__(self):

        return hash(str(self))

    def exists(self):

        return os.path.exists(str(self))

    def basename(self):

        return Path(self.path[-1:])

    def dirname(self):

        return Path(self.path[0:-1])

    def touch(self):

        self.dirname().mkpath()
        if not os.path.exists(str(self)):
            open(str(self), 'w').close()

    def mkpath(self):

        if not os.path.exists(str(self)):
            os.makedirs(str(self))

    def __eq__(self, rhs):

        if rhs.__class__ != Path:
            rhs = Path(rhs)
        return self.path == rhs.path

    def __div__(self, rhs):

        rhs = Path(rhs)

        if self == '.':
            return rhs
        if rhs == Path('.'):
            return clone(self)

        res = clone(self)
        res.path += rhs.path
        return res

    def strip_prefix(self, rhs):

        if self.path[0:len(rhs.path)] != rhs.path:
            raise Exception("%s is not a prefix of %s" % (rhs, self))
        self.path = self.path[len(rhs.path):]
        if not self.path:
            self.path = ['.']

CACHEDIR = Path('.drake')

class DepFile:

    def __init__(self, builder, name):

        self.builder = builder
        self.name = name
        builder.dsts.sort()
        self._files = {}
        self._sha1 = {}


    def files(self):

        return self._files.values()


    def sha1s(self):

        return self._sha1


    def register(self, node):

        self._files[str(node.path())] = node


    def path(self):

        return self.builder.cachedir() / self.name


    def read(self):

        res = []

        self.path().touch()
        for line in open(str(self.path()), 'r'):
            sha1 = line[:40]
            src = Path(line[41:-1]) # Chomp the \n
            self._sha1[str(src)] = sha1

    def up_to_date(self):

        for path in self._sha1:
            assert str(path) in Node.nodes
            h = hashlib.sha1(open(str(node(path).path())).read()).hexdigest()
            if self._sha1[path] != h:
                debug('  Execution needed because hash is outdated: %s.' % path)
                return False

        return True


    def update(self):

        f = open(str(self.path()), 'w')
        for path in self._files:
            h = hashlib.sha1(open(path).read()).hexdigest()
            print >>f, '%s %s' % (h, self._files[path].id())

    def __repr__(self):

        return 'DepFile(%s)' % repr(self.node)

    def __str__(self):

        return 'DepFile(%s)' % self.node



class Node:


    nodes = {}
    uid = 0
    extensions = {}


    def __init__(self, path):

        if path.__class__ == str:
            path = Path(path)

        self.sym_path = path
        self.src_path = prefix() / path

        self.uid = Node.uid
        Node.uid += 1

        self.builder = None
        self.srctree = srctree()
        Node.nodes[str(self.id())] = self


    def clean(self):

        if self.builder is not None:
            self.builder.clean()
            if self.path().exists():
                print 'Deleting %s' % self
                os.remove(str(self.path()))


    def path(self):

        if self.src_path.absolute:
            assert self.builder is None
            return self.src_path

        if self.builder is None:
            return self.srctree / self.src_path
        else:
            return self.src_path


    def id(self):

        return self.src_path


    def build(self):

        debug('Building %s' % self)
        if self.builder is None:
            if not self.path().exists():
                raise Exception('no builder to make %s' % self)
            return

        self.builder.run()


    def __setattr__(self, name, value):

        if name == 'builder' and 'builder' in self.__dict__:
            del self.nodes[str(self.id())]
            self.__dict__[name] = value
            self.nodes[str(self.path())] = self
        else:
            self.__dict__[name] = value


    def __repr__(self):

        return str(self.path())


    def __str__(self):

        return str(self.path())


    def __lt__(self, rhs):

        return self.path() < rhs.path()



def node(path):

    if path.__class__ != Path:
        path = Path(path)

    if str(path) in Node.nodes:
        return Node.nodes[str(path)]

    if path.extension not in Node.extensions:
        raise Exception('unknown file type: %s' % path)

    return Node.extensions[path.extension](path)



def nodes(*paths):

    return map(node, paths)




class Builder:


    builders = []
    uid = 0

    name = 'build'
    _deps_handlers = {}

    @classmethod
    def register_deps_handler(self, name, f):
        self._deps_handlers[name] = f

    def __init__(self, srcs, dsts):

        assert srcs.__class__ == list
        self.srcs = {}
        for src in srcs:
            self.add_src(src)
#        self.srcs = srcs
        self.dsts = dsts
        for dst in dsts:
            if dst.builder is not None:
                raise Exception('builder redefinition for %s' % dst)
            dst.builder = self

        self.uid = Builder.uid
        Builder.uid += 1
        Builder.builders.append(self)

        self._depfiles = {}
        self._depfile = DepFile(self, 'drake')
        self.built = False
        self.dynsrc = {}


    def cachedir(self):

        path = self.dsts[0].path()
        res = prefix() / path.dirname() / CACHEDIR / path.basename()
        res.mkpath()
        return res


    def dependencies(self):

        return []


    def depfile(self, name):

        if name not in self._depfiles:
            self._depfiles[name] = DepFile(self, name)
        return self._depfiles[name]


    def add_dynsrc(self, name, node, data = None):

        self.depfile(name).register(node)
        self.dynsrc[str(node.path())] = node


    def run(self):

        # If we were already executed, just skip
        if self.built:
            debug('  Already built in this run.')
            return

        # The list of static dependencies is now fixed
        for path in self.srcs:
            self._depfile.register(self.srcs[path])

        # See Whether we need to execute or not
        execute = False

        # Reload dynamic dependencies
        if not execute:
            for f in os.listdir(str(self.cachedir())):
                if f == 'drake':
                    continue
                depfile = self.depfile(f)
                depfile.read()
                handler = self._deps_handlers[f]

                for path in depfile.sha1s():

                    if path in self.srcs or path in self.dynsrc:
                        continue

                    if path in Node.nodes:
                        node = Node.nodes[path]
                    else:
                        node = handler(self, path, None)

                    self.add_dynsrc(f, node, None)

        # Build all dependencies
        for path in self.srcs:
            self.srcs[path].build()
        for path in self.dynsrc:
            self.dynsrc[path].build()

        # If any target is missing, we must rebuild.
        if not execute:
            for dst in self.dsts:
                if not dst.path().exists():
                    debug('  Execution needed because of missing target: %s.' % dst.path())
                    execute = True

        # Load static dependencies
        self._depfile.read()

        # If a new dependency appeared, we must rebuild.
        if not execute:
            for p in self.srcs:
                path = self.srcs[p].id()
                if path not in self._depfile._sha1:
                    debug('  Execution needed because a new dependency appeared: %s.' % path)
                    execute = True
                    break

        # Check if we are up to date wrt all dependencies
        if not execute:
            if not self._depfile.up_to_date():
                execute = True
            for f in self._depfiles:
                if not self._depfiles[f].up_to_date():
                    execute = True


        if execute:

            # Regenerate dynamic dependencies
            self.dynsrc = {}
            self._depfiles = {}
            self.dependencies()
            for path in self.dynsrc:
                self.dynsrc[path].build()

            if not self.execute():
                raise Exception('%s failed' % self.name)
            for dst in self.dsts:
                if not dst.path().exists():
                    raise Exception('%s wasn\'t created by %s' % (dst, self))
            self._depfile.update()
            for name in self._depfiles:
                self._depfiles[name].update()
            self.built = True
        else:
            debug('  Everything is up to date.')


    def execute(self):

        raise Exception('execute is not implemented for %s' % self)


    def clean(self):

        for path in self.srcs:
            self.srcs[path].clean()


    def __str__(self):

        return self.__class__.__name__


    def cmd(self, fmt, *args):

        rg = re.compile('\'')

        args = map(str, args)
        for arg in args:
            if rg.match(arg):
                pass
        command = fmt % tuple(args)
        print command
        return os.system(command) == 0


    def add_src(self, src):

        self.srcs[str(src.path())] = src


    def all_srcs(self):

        res = []
        for src in self.srcs.values() + self.dynsrc.values():
            res.append(src)
            if src.builder is not None:
                res += src.builder.all_srcs()
        return res



class ShellCommand(Builder):

    def __init__(self, srcs, dsts, fmt, *args):

        Builder.__init__(self, srcs, dsts)
        self.fmt = fmt
        self.args = args

    def execute(self):

        return self.cmd(self.fmt, *self.args)

def shell_escape(str):

    # FIXME: escape only if needed
    # FIXME: complete that
    return '"%s"' % str

_prefix = Path('.')

def prefix():
    return _prefix

_srctree = Path('.')

def set_srctree(path):

    global _srctree
    _srctree = Path(path)

def srctree():

    global _srctree
    return _srctree

def strip_srctree(path):

    global _srctree
    res = clone(path)
    if not path.absolute:
        res.strip_prefix(_srctree)
    return res

class Module:

    def __init__(self, globals):

        self.globals = globals

    def __getattr__(self, name):

        return self.globals[name]


def include(path, *args, **kwargs):

    global _prefix

    path = Path(path)
    previous_prefix = _prefix
    _prefix = _prefix / path
    res = raw_include(str(previous_prefix / path / 'drakefile.py'), *args, **kwargs)
    _prefix = previous_prefix
    return res


def raw_include(path, *args, **kwargs):

    g = {}
    execfile(str(srctree() / path), g)
    res = Module(g)
    res.configure(*args, **kwargs)
    return res

def dot(*filters):

    def take(path):
        for filter in filters:
            if re.compile(filter).search(path):
                return False
        return True

    print 'digraph'
    print '{'
    for path in Node.nodes:
        if take(path):
            node = Node.nodes[path]
            print '  node_%s [label="%s"]' % (node.uid, node.path())
    print
    for builder in Builder.builders:
        print '  builder_%s [label="%s", shape=rect]' % (builder.uid, builder.__class__)
        for src in builder.srcs:
            if take(src):
                print '  node_%s -> builder_%s' % (builder.srcs[src].uid, builder.uid)
        for src in builder.dynsrc:
            if take(src):
                print '  node_%s -> builder_%s' % (builder.dynsrc[src].uid, builder.uid)
        for dst in builder.dsts:
            if take(str(dst.path())):
                print '  builder_%s -> node_%s' % (builder.uid, dst.uid)
    print '}'

# Architectures
x86 = 0

# OSes
linux = 0
macos = 1
windows = 2
