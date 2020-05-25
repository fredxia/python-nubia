
import re
import sys
import shlex
import copy
import pdb
import traceback

def isInteractive(fh):
    return fh.isatty() and not fh.closed

def exceptionHook(ex, val, tr):
    traceback.print_exception(ex, val, tr)
    if isInteractive(sys.stderr) and isInteractive(sys.stdout):
        pdb.post_mortem(tr)

sys.excepthook = exceptionHook

# ================================
# Exception
# ================================

class KeywordException(Exception):
    pass

class PathException(Exception):
    pass

class CommandException(Exception):
    pass

class ParseException(Exception):
    pass

# ================================
# Command Node Classes
# ================================

terminal_node = None

def is_keyword_str(s):
    return re.match(r"^\w(\w|\d)+$", s) is not None

def is_value_token(s):
    return re.match(r"^<\w(\w|\d)+>$", s) is not None

def tokenize_cmd_spec_string(cmd_str):
    items = shlex.split(cmd_str)
    tokens = []
    for item in items:
        if not item.startswith("[") and not item.endswith("]"):
            tokens.append(item)
        elif item in [ "[",  "]" ]:
            tokens.append(item)
        elif item.startswith("["):
            tokens.append("[")
            tokens.append(item.strip("["))
        else:
            tokens.append(item.rstrip("]"))
            tokens.append("]")
    return tokens

class TokenNode:

    Flag_Optional = 0x01
    Flag_Promoted = 0x02

    def __init__(self, name, help_string=None, optional=False):
        self.name = name
        self.help_string = help_string
        self.prev_tokens = []
        self.next_tokens = []
        self.flags = TokenNode.Flag_Optional if optional else 0
        self.result = None # hold resolved value during parsing

    def is_root(self):
        return not self.prev_tokens

    def get_root(self):
        return self if self.is_root() else self.prev_tokens[0].get_root()

    def get_command(self):
        root = self.get_root()
        return root if isinstance(root, Command) else None
        
    def is_leaf(self):
        return not self.next_tokens or \
            (len(self.next_tokens) == 1 and self.next_tokens[0].is_terminal_node())

    def is_optional(self):
        return self.flags & TokenNode.Flag_Optional != 0

    def is_promoted(self):
        return self.flags & TokenNode.Flag_Promoted != 0

    def is_keyword(self):
        # pylint: disable=R0201
        return False
        # pylint: enable=R0201

    def is_value(self):
        # pylint: disable=R0201
        return False
        # pylint: enable=R0201

    def is_terminal_node(self):
        # pylint: disable=R0201
        return False
        # pylint: enable=R0201

    def may_terminate(self):
        if not self.get_command():
            return False
        return self in self.get_command().terminal_node.prev_tokens

    def terminate(self):
        for c in self.next_tokens:
            if c.is_terminal_node():
                c.result = "__terminate__"
                return
        assert False, "Node %s cannot terminate" % self.path_string()

    def keyword(self):
        assert self.is_keyword()
        return self.name

    def path_string(self):
        '''String of one possible path'''
        if not self.prev_tokens:
            return self.name
        return self.prev_tokens[0].path_string() + "/" + self.name

    def terminate_paths(self):
        if self.is_terminal_node():
            return
        command = self.get_command()
        assert command is not None, "Node is not in a command %s" % self.name
        for c in self.next_tokens:
            if c.is_terminal_node():
                continue
            if c.is_leaf():
                if not c.next_tokens:
                    c.next_tokens.append(command.terminal_node)
                    command.terminal_node.prev_tokens.append(c)
            else:
                c.terminate_paths()

    def clear_result(self):
        self.result = None
        for c in self.next_tokens:
            c.clear_result()

    def dump_node(self, indent=0):
        node_str = " " * indent
        if self.is_keyword():
            binding = self.get_command().value_binding(self.keyword())
            if binding is True:
                value = self.value_child()
                s = "%s <%s>" % (self.keyword(), value.name)
                if value.may_terminate():
                    s += " <cr>"
                node_str += s if not self.is_optional() else "[" + s + "]"
                print(node_str)
                if not value.is_leaf():
                    value.print_node(indent + 4)
            else:
                s = self.keyword()
                if self.may_terminate():
                    s += " <cr>"
                node_str += s if not self.is_optional() else "[" + s + "]"
                print(node_str)
                for c in self.next_tokens:
                    if c.is_terminal_node():
                        continue
                    c.print_node(indent + 4)
        else:
            for c in self.next_tokens:
                if c.is_terminal_node():
                    continue
                c.print_node(indent + 4)

    def value_child(self):
        assert self.is_keyword() and \
            self.get_command().value_binding(self.keyword()) is True
        for c in self.next_tokens:
            if c.is_value():
                return c
        raise PathException("value child not found")

    def next_is_internal(self, keyword, help_string, value_node, optional):

        if value_node:
            # Must be a freshly created value node
            assert not value_node.prev_tokens and not value_node.next_tokens

        # Registered command is frozen and cannot accept new args
        command = self.get_command()
        assert command and not command.is_registered()

        has_binding = command.value_binding(keyword)
        if has_binding is not None:
            if has_binding is True and not value_node:
                raise PathException(
                    "%s is a value key. Must be followed by a value" % keyword)
            if has_binding is False and value_node:
                raise PathException(
                    "%s is not a value key. Cannot be followed by a value" % (
                        keyword))

        # Terminate all other child nodes if not yet
        for c in self.next_tokens:
            if c.is_terminal_node():
                continue
            assert c.is_keyword()
            c.terminate_paths()
            if c.keyword() == keyword:
                # If keyword is found, merge instead of creating a new node.
                # optional flag and help string must be the same
                if c.is_optional() != optional:
                    raise PathException("Conflict in optional attribute %s" % (
                        keyword))
                if help_string and c.help_string() != help_string:
                    raise KeywordException("Help string conflict %s: %s" % (
                        help_string, c.help_string()))
                if has_binding is True:
                    # value node should be the same
                    if not c.value_child().name() == value_node.name():
                        raise PathException("Conflict in value node %s: %s" % (
                            c.value_child().name(), value_node.name()))
                    return c.value_child()
                return c

        keyword_node = Keyword(keyword, help_string=help_string,
                               optional=optional)
        if value_node:
            keyword_node.next_tokens.append(value_node)
            value_node.prev_tokens = [keyword_node]

        self.next_tokens.append(keyword_node)
        keyword_node.prev_tokens = [self]
        if has_binding is None:
            command.set_value_binding(keyword, value_node is not None)
        return keyword_node if not value_node else value_node

    def next_are(self, args, optional=False):
        # next_are is a separate call because it cannot be chained
        nodes = []
        for arg in args:
            assert isinstance(arg, tuple)
            node = self.next_is(*arg, optional=optional)
            nodes.append(node)
        return nodes

    def next_is(self, *args, **kwargs):
        '''
        Dynamic arguments allowing these call formats:

            self.next_is("cmd_keyword", optional=True)
            self.next_is("cmd_keyword", "keyword help", optional=True)
            self.next_is("cmd_keyword", value_node, optional=True)
            self.next_is("cmd_keyword", "keyword help", value_node, optional=True)
            self.next_is("cmd_keyword", "<value>", optional=True)
            self.next_is("cmd_keyword", "keyword help", "<value>", optional=True)
            self.next_is(cmd_keyword_node)
            self.next_is(cmd_keyword_node, "<value>", optional=True)
            self.next_is(cmd_keyword_node, value_node, optional=True)
        '''
        assert not self.is_terminal_node()
        assert len(args) > 0 and len(args) < 4

        keyword = args[0]
        keyword_help = None
        value = None
        optional = False

        command = self.get_command()
        if not command:
            raise PathException("Node is not in a command: %s" % self.name)

        if isinstance(keyword, Keyword):
            if len(args) == 2:
                if isinstance(args[1], ValueNode):
                    value = args[1]
                else:
                    value = get_value_of_token(command.context_name, args[1])
                    assert value, "Value %s not found" % args[1]
            else:
                assert len(args) == 1
            keyword_help = keyword.help_string
            optional = keyword.is_optional() # node may have optional set
            keyword = keyword.keyword()
        elif len(args) == 1:
            pass
        elif len(args) == 2:
            if isinstance(args[1], str):
                value = get_value_of_token(command.context_name, args[1])
                if not value:
                    keyword_help = args[1]
            elif isinstance(args[1], ValueNode):
                value = args[1]
        else:
            keyword_help = args[1]
            if isinstance(args[2], str):
                value = get_value_of_token(command.context_name, args[2])
                assert value, "Value %s not found" % args[2]

        optional = kwargs.get("optional", optional)
        return self.next_is_internal(keyword, keyword_help, value, optional)

    def evaluate(self, tokens):
        '''
        Try to determine a path with the tokens. If path found return binding
        values. Otherwise return None.
        '''
        assert self.is_root()
        self.clear_result()
        assert tokens[0] == self.keyword()
        r = self.walk(tokens, 1)
        if not r:
            self.clear_result()
            return None
        self.result = self.keyword()
        # Collect bindings
        values = { "__tokens__" : tokens }
        node = self
        while node:
            if node.result is None:
                continue
            if node.is_value():
                values[node.name] = node.result
            if node.is_leaf():
                break
            for c in node.next_tokens:
                if c.result is not None:
                    node = c
                    break
        self.clear_result()
        return values

    def walk(self, tokens, pos):
        '''
        Walk path with tokens. Save resolved value in 'result'. It is
        guarenteed that at most only one terminating path exists that matches
        all tokens.
        '''
        token = tokens[pos]
        for c in self.next_tokens:
            if c.is_terminal_node():
                continue
            if c.consume(token):
                if token == tokens[-1]:
                    # All tokens consumed. Abandon if c cannot terminate command
                    if c.may_terminate():
                        c.terminate()
                        return True
                elif c.is_leaf():
                    # more tokens but no child node to walk
                    if self.get_command().discard_trailing_tokens:
                        return True
                    raise PathException("Unmatched trailing tokens: %s" % (
                        tokens[1:]))
                elif c.walk(tokens, pos + 1):
                    return True
            # Failed to walk path along this node
            c.clear_result()
        return False

class TerminalNode(TokenNode):
    def __init__(self):
        TokenNode.__init__(self, "<Terminal>", "")

    def is_terminal_node(self):
        return True

class Keyword(TokenNode):
    def __init__(self, keyword, help_string=None, optional=False):
        TokenNode.__init__(self, keyword, help_string, optional=optional)

    def is_keyword(self):
        return True

    def consume(self, a_str):
        if self.keyword() == a_str:
            self.result = self.keyword()
            return True
        return False

class ValueNode(TokenNode):
    def __init__(self, name, help_string=None):
        TokenNode.__init__(self, name, help_string)

    def is_value(self):
        return True

    def value_name(self):
        return "<" + self.name + ">"

class IntValue(ValueNode):
    def __init_(self, name, help_string=None):
        super().__init__(self, name, help_string)

    def consume(self, a_str):
        try:
            v = int(a_str)
            self.result = v
            return True
        except ValueError:
            return False

class IntRange(ValueNode):
    def __init__(self, name, low, high, help_string=None):
        super().__init__(name, help_string)
        self.low = int(low)
        self.high = int(high)

    def consume(self, a_str):
        try:
            v = int(a_str)
            if self.low <= v < self.high:
                self.result = v
                return True
            return False
        except ValueError:
            return False

class Command(Keyword):

    def __init__(self, keyword, help_string=None, context=None):
        Keyword.__init__(self, keyword, help_string=help_string)
        self.keyword_value_binding = {}
        self.discard_trailing_tokens = False
        self.context_name = context if context else global_context_name
        self.all_paths = None
        self.terminal_node = TerminalNode()

    def value_binding(self, keyword):
        if not keyword in self.keyword_value_binding:
            return None
        return self.keyword_value_binding[keyword]

    def set_value_binding(self, keyword, is_value):
        assert keyword not in self.keyword_value_binding
        self.keyword_value_binding[keyword] = is_value

    def is_registered(self):
        return get_registered_command(self.context_name, self.name) is not None

    def get_path(self, path_string):
        node_names = path_string.split("/")
        assert self.is_root() and node_names[0] == self.name
        if len(node_names) == 1:
            return self
        node = self
        node_names.pop(0)
        while node_names:
            found = False
            name = node_names.pop(0)
            for c in node.next_tokens:
                if c.name == name:
                    if c.is_value():
                        print("Warning: match value with node name %s" % name)
                    node = c
                    found = True
                elif c.is_value() and c.value_name() == name:
                    node = c
                    found = True
                if found:
                    break
            if not found:
                break
        return None if node_names else node

    def collect_paths(self):
        '''Collect all paths by DFS walk. Check cycle.'''
        all_paths = set([])
        def dfs_walk(node, path):
            if node.is_leaf():
                path_str = " ".join([p.keyword() if p.is_keyword() \
                                     else p.value_name() for p in path])
                assert path_str not in all_paths
                all_paths.add(path_str)
            else:
                for e in node.next_tokens:
                    if e.is_terminal_node():
                        continue
                    if e in path:
                        raise PathException(
                            "Command %s arg cycle detected at %s" % (
                                self.name, e.name))
                    path.append(e)
                    dfs_walk(e, path)
                    path.pop(-1)

        path = [self]
        dfs_walk(self, path)
        return all_paths

    def check_paths(self):

        def promote_nodes(from_nodes, to_nodes):
            for from_node in from_nodes:
                for to_node in to_nodes:
                    if from_node not in to_node.next_tokens:
                        assert to_node not in from_node.prev_tokens
                        to_node.next_tokens.append(from_node)
                        from_node.prev_tokens.append(to_node)
                        from_node.flags |= TokenNode.Flag_Promoted
                        
        def terminate_and_promote(node):
            if node.is_leaf():
                if not node.next_tokens:
                    node.next_tokens.append(self.terminal_node)
                return
            for e in node.next_tokens:
                if not e.is_terminal_node():
                    terminate_and_promote(e) # DFS
            if node.is_keyword() and node.is_optional():
                # need to promote
                has_binding = self.value_binding(node)
                if has_binding:
                    from_nodes = node.value_child().next_tokens
                else:
                    from_nodes = node.next_tokens
                # to nodes may be immediate up level or two level up if the
                # up level node is a value node
                to_nodes = []
                for prev in node.prev_tokens:
                    if prev.is_keyword():
                        to_nodes.append(prev)
                    else:
                        assert prev.is_value() and prev.prev_tokens[0].is_keyword()
                        to_nodes.append(prev.prev_tokens[0])
                promote_nodes(from_nodes, to_nodes)

        terminate_and_promote(self)
        self.all_paths = self.collect_paths()

    def merge(self, new_node_chain):
        '''
        Merge a newly created single-link cmd node chain into existing cmd
        node tree.
        '''
        assert isinstance(new_node_chain, Command) and \
            self.keyword() == new_node_chain.keyword() and \
            not self.is_registered()

        if new_node_chain.is_leaf():
            return self

        # Verify node chain is a chain
        new_node = new_node_chain
        while new_node.next_tokens:
            if not len(new_node.next_tokens) == 1:
                raise PathException(
                    "Command node chain is not a single-link chain %s" % (
                        new_node.name))
            new_node = new_node.next_tokens[0]

        def is_kv_node(node):
            return node.is_keyword() and not node.is_leaf() and \
                node.next_tokens[0].is_value()

        new_node = new_node_chain.next_tokens[0]
        current_node = self

        while new_node:
            if is_kv_node(new_node):
                # Add both the keyword and value nodes
                node = current_node.next_is(new_node,
                                            new_node.next_tokens[0],
                                            optional=new_node.is_optional(),
                                            merge=True)
                if not node:
                    return None
                current_node = node
                if new_node.next_tokens[0].is_leaf():
                    break # end of node chain
                new_node = new_node.next_tokens[0].next_tokens[0]
            else:
                node = current_node.next_is(new_node,
                                            optional=new_node.is_optional(),
                                            merge=True)
                if not node:
                    return None
                current_node = node
                if not new_node.next_tokens:
                    break # end of node chain
                new_node = new_node.next_tokens[0]
        return current_node

    def print_commands(self):
        for p in self.all_paths:
            print(p)

# ================================
# Parsing and parsed results
# ================================

global_context_name = "__global_context__"

# Context name => keyword token and help string
registered_keywords = { global_context_name : {} }

# Context name => value tokens
registered_values = { global_context_name : {} }

# Context name => registered commands
registered_commands = { global_context_name : {} }

def default_command_handler(context, tokens, values):
    print("default_command_handler, context %s, tokens %s, values %s" % (
        context.name, tokens, values))

def register_keyword(*args):
    context_name = args[0] if len(args) == 3 else global_context_name
    keyword = args[0] if len(args) == 2 else args[1]
    help_string = args[1] if len(args) == 2 else args[2]
    if context_name not in registered_keywords:
        registered_keywords[context_name] = { keyword : help_string }
        return
    assert keyword not in registered_keywords[context_name]
    registered_keywords[context_name][keyword] = help_string

def get_keyword_help_string(context_name, keyword):
    if not context_name in registered_keywords:
        return None
    return registered_keywords[context_name].get(keyword, None)

def register_value_token(*args):
    '''
        register_value_token(value_node)    
        register_value_token("context_name", value_node)

        Save a copy of a clean value node.
    '''
    context_name = args[0] if len(args) == 2 else global_context_name
    value_node = args[0] if len(args) == 1 else args[1]
    assert isinstance(value_node, ValueNode)
    node = copy.deepcopy(value_node)
    node.prev_tokens = []
    node.next_tokens = []
    if context_name not in registered_values:
        registered_values[context_name] = { node.name : node }
        return
    assert node.name not in registered_values[context_name]
    registered_values[context_name][node.name] = node

def get_value_of_token(context_name, token):
    '''Return a copy of registered value node so it can be used freely'''
    if token.startswith("<"):
        token = token.strip("<").rstrip(">")
    if context_name in registered_values and \
       token in registered_values[context_name]:
        return copy.deepcopy(registered_values[context_name][token])
    if token in registered_values[global_context_name]:
        return copy.deepcopy(registered_values[global_context_name][token])
    return None

def parse_cmd_spec_string(context_name, cmd_str):
    '''
    Parser a command spec string. Return a chain of nodes, with the first
    node being a Command node.
    '''
    tokens = tokenize_cmd_spec_string(cmd_str)
    cmd = tokens.pop(0)
    if not is_keyword_str(cmd):
        raise ParseException("Invalid command string %s" % cmd)
    if get_registered_command(context_name, cmd):
        raise ParseException("Command already registered %s in context %s" % (
            cmd, context_name))

    cmd_node = Command(cmd, get_keyword_help_string(context_name, cmd))

    optional = False
    node = cmd_node
    while tokens:
        token = tokens.pop(0)
        if is_keyword_str(token):
            keyword_node = Keyword(token,
                                   get_keyword_help_string(context_name, token),
                                   optional=optional)
            if not tokens or not is_value_token(tokens[0]):
                node = node.next_is(keyword_node)
            elif is_value_token(tokens[0]):
                token = tokens.pop(0)
                value = get_value_of_token(context_name, token)
                if value is None:
                    raise ParseException(
                        "Value token %s not defined" % token)
                value_node = copy.deepcopy(value)
                node = node.next_is(keyword_node, value_node)
        elif token == "[":
            if optional:
                raise ParseException("Unbalanced optional bracket")
            pdb.set_trace()
            optional = True
        elif token == "]":
            if not optional:
                raise ParseException("Unbalanced optional bracket")
            optional = False
        elif node == cmd_node:
            # special case. cmd itself followed by value
            value_node = get_value_of_token(context_name, token)
            if value_node:
                cmd_node.next_tokens.append(value_node)
                value_node.prev_tokens.append(cmd_node)
                node = value_node
                cmd_node.set_value_binding(cmd, True)
            else:
                raise ParseException("Parse error at %s" % token)
        else:
            assert False, "Parse error at %s" % token
    if optional:
        raise ParseException("Unbalanced optional bracket")
    return cmd_node

def register_command_node(cmd_node, context_name, handler):
    assert not cmd_node.is_registered()

    if context_name not in registered_commands:
        registered_commands[context_name] = {}

    keyword = cmd_node.keyword()
    if keyword in registered_commands[context_name]:
        raise PathException("Command %s exists in context %s" % (
            keyword, context_name))

    cmd_node.check_paths()
    
    cmd_node.context_name = context_name
    registered_commands[context_name][cmd_node.name] = (cmd_node, handler)
    return cmd_node

def register_command(*args):
    '''
    Dynamic arguments can take the following formats:

        register_command(cmd_node)
        register_command(cmd_node, context_name)
        register_command(cmd_node, handler)
        register_command(cmd_node, context_name, handler)

        register_command(cmd_spec_str)
        register_command(cmd_spec_str, context_name)
        register_command(cmd_spec_str, handler)
        register_command(cmd_spec_str, context_name, handler)

        register_command(cmd_spec_str_list,
        register_command(cmd_spec_str_list, handler)
        register_command(cmd_spec_str_list, context_name)
        register_command(cmd_spec_str_list, context_name, handler)
    '''
    assert len(args) > 0 and len(args) < 4

    if isinstance(args[0], Command):
        cmd_node = args[0]
        if len(args) == 1:
            context_name = cmd_node.context_name if cmd_node.context_name \
                           else global_context_name
            return register_command_node(cmd_node,
                                         context_name,
                                         default_command_handler)
        if len(args) == 2:
            if isinstance(args[1], str):
                context_name = args[1]
                if cmd_node.context_name and \
                   cmd_node.context_name != context_name:
                    raise PathException(
                        "Conflict in command %s context %s, %s" % (
                            cmd_node.name, cmd_node.context_name, context_name))
                return register_command_node(cmd_node,
                                             context_name,
                                             default_command_handler)
            # args[1] is handler
            context_name = cmd_node.context_name if cmd_node.context_name \
                           else global_context_name
            return register_command_node(cmd_node, context_name, args[1])
        if len(args) == 3:
            assert isinstance(args[1], str)
            if cmd_node.context_name and cmd_node.context_name != args[1]:
                raise PathException(
                    "Conflict in command %s context %s, %s" % (
                        cmd_node.name, cmd_node.context_name, args[1]))
            return register_command_node(cmd_node, args[1], args[2])

    if len(args) == 1:
        if isinstance(args[0], str):
            return register_command([args[0]],
                                    global_context_name,
                                    default_command_handler)
        return register_command(args[0],
                                global_context_name,
                                default_command_handler)
    if len(args) == 2:
        if isinstance(args[1], str):
            return register_command([args[0]], args[1], default_command_handler)
        return register_command(args[0], global_context_name, args[1])

    # len(args) == 3
    if isinstance(args[0], str):
        return register_command([args[0]], args[1], args[2])

    # len(args) == 3 and register list of command specs
    assert isinstance(args[0], list)

    new_commands = {}
    context_name, handler = args[1], args[2]

    for cmd_str in args[0]:
        new_cmd_node = parse_cmd_spec_string(context_name, cmd_str)
        if new_cmd_node.name in new_commands:
            # cmd already exist. use the existing one as starting node and
            # merge new_cmd_node chain into cmd_node
            cmd_node = new_commands[new_cmd_node.name]
            cmd_node.merge(new_cmd_node)
        else:
            new_commands[new_cmd_node.name] = new_cmd_node
    nodes = []
    for cmd_node in new_commands.values():
        n = register_command_node(cmd_node, context_name, handler)
        nodes.append(n)
    return nodes

def get_registered_command(*args):
    '''
        get_registered_command(cmd)
        get_registered_command(context_name, cmd)
    '''
    context_name = args[0] if len(args) == 2 else global_context_name
    cmd_name = args[1] if len(args) == 2 else args[0]
    if not context_name in registered_commands:
        return None
    return registered_commands[context_name].get(cmd_name, None)

def search_registered_command(*args):
    pass # TBD

# ================================
# Context
# ================================

class Context:

    def __init__(self, name):
        # TBD pop up policy, recursive or root context only
        self.name = name
        self.commands = {}
        self.container_context = None
        self.nest_context = None
        self.runtime = None # for top-level context only
        self.command_handler = None

    def on_enter(self):
        pass

    def on_exit(self, commit=False):
        pass

    def set_runtime(self, runtime):
        assert self.container_context is None and runtime.context == self
        self.runtime = runtime

    def get_runtime(self):
        if self.container_context:
            return self.container_context.runtime()
        return self.runtime

    def get_prompt(self):
        # pylint: disable=R0201
        return "#"
        # pylint: enable=R0201

    def push_context(self, context):
        assert self.nest_context is None
        self.nest_context = context
        context.container_context = self
        self.nest_context.on_enter()

    def pop_context(self, commit=False):
        if self.nest_context:
            self.nest_context.pop_context(commit)
            self.nest_context = None
        self.on_exit(commit)

    def evaluate_command(self, cmd_str, run=True):
        tokens = shlex.split(cmd_str)
        cmd = tokens[0]
        if not cmd in self.commands:
            # If cmd not found in current context evaluate in parent context
            if not self.container_context:
                return None
            context = self.container_context.evaluate_command(
                cmd_str, run=False)
            if not context:
                return None
            return context.evaluate_command(cmd_str, run=run)
        cmd_node = self.commands[cmd][0]
        values = cmd_node.evaluate(tokens)
        if not values:
            return None
        if not run:
            return values
        # If run is True pop all contexts
        if self.nest_context:
            self.nest_context.exit_context(commit=False)
            self.nest_context = None
        return self.commands[cmd][1](self, tokens, values)

# Default context
default_global_context = Context(global_context_name)

# ================================
# RunTime
# ================================

class RunTime:
    def __init__(self, name, context=default_global_context):
        self.name = name
        self.root_context = context

    def evaluate_command(self, cmd_str):
        '''
        Evaluate a command string and call handler with binding values if
        cmd_str matches a registered a command in the context chain.
        '''
        return self.current_context().evaluate_command(cmd_str)

    def current_context(self):
        context = self.root_context
        while context.nest_context:
            context = context.nest_context
        return context
