
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

def is_keyword_str(s):
    return re.match(r"^\w(\w|\d)+$", s)

def is_value_token(s):
    return re.match(r"^<\w(\w|\d)+>$", s)

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
    def __init__(self, name, help_string=None, optional=False):
        self.name = name
        self.help_string = help_string
        self.parent_node = None
        self.child_nodes = []
        self.optional = optional
        self.result = None # hold resolved value during parsing

    def is_root(self):
        return self.parent_node is None

    def get_root(self):
        if self.parent_node:
            return self.parent_node.get_root()
        return self

    def is_leaf(self):
        return not self.child_nodes or \
            (len(self.child_nodes) == 1 and \
             self.child_nodes[0].is_terminal_node())

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
        for c in self.child_nodes:
            if c.is_terminal_node():
                return True
        return False

    def terminate(self):
        for c in self.child_nodes:
            if c.is_terminal_node():
                c.result = "__terminate__"
                return
        assert False, "Node %s cannot terminate" % self.path_string()

    def is_optional(self):
        return self.optional

    def keyword(self):
        assert self.is_keyword()
        return self.name

    def path_string(self):
        if not self.parent_node:
            return self.name
        return self.parent_node.path_string() + "/" + self.name

    def get_path(self, path_string):
        node_names = path_string.split("/")
        assert self.is_root() and node_names[0] == self.name
        node = self
        node_names.pop(0)
        if not node_names:
            return self
        while node_names:
            found = False
            name = node_names.pop(0)
            for c in node.child_nodes:
                if c.is_terminal_node():
                    continue
                if c.name == name:
                    node = c
                    found = True
                    break
            if not found:
                break
        return None if node_names else node

    def collect_paths(self):
        assert self.is_terminal_node()
        paths = []
        node = self.parent_node
        root = self.get_root()
        while node:
            if not paths:
                paths.append([node])
            else:
                for p in paths:
                    p.append(node)
            if node.is_optional():
                assert node.is_keyword()
                # Duplicate current paths and delete itself from the copy
                binding = root.value_binding(node.keyword())
                copy_paths = []
                for p in paths:
                    p2 = p.copy()
                    p2.pop()
                    if binding:
                        assert p2[-1].is_value()
                        p2.pop()
                    copy_paths.append(p2)
                paths.extend(copy_paths)
            node = node.parent_node
        for p in paths:
            p.reverse()
        return paths

    def terminate_paths(self, collect_terminal_nodes=None):
        for c in self.child_nodes:
            if c.is_terminal_node():
                if collect_terminal_nodes is not None:
                    collect_terminal_nodes.append(c)
                continue
            if c.is_leaf():
                if c.child_nodes:
                    if collect_terminal_nodes:
                        collect_terminal_nodes.append(c.child_nodes[0])
                else:
                    terminal_node = TerminalNode()
                    c.child_nodes.append(terminal_node)
                    terminal_node.parent_node = c
                    if collect_terminal_nodes is not None:
                        collect_terminal_nodes.append(terminal_node)
            else:
                c.terminate_paths(collect_terminal_nodes)

    def clear_result(self):
        self.result = None
        for c in self.child_nodes:
            c.clear_result()

    def dump_node(self, indent=0):
        node_str = " " * indent
        if self.is_keyword():
            binding = self.get_root().value_binding(self.keyword())
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
                for c in self.child_nodes:
                    if c.is_terminal_node():
                        continue
                    c.print_node(indent + 4)
        else:
            for c in self.child_nodes:
                if c.is_terminal_node():
                    continue
                c.print_node(indent + 4)

    def value_child(self):
        assert self.is_keyword() and \
            self.get_root().value_binding(self.keyword()) is True
        for c in self.child_nodes:
            if c.is_value():
                return c
        raise PathException("value child not found")

    def next_are(self, args, optional=False):
        '''
        next_are is a separate call because it cannot be chained.
        '''
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
            self.next_is("cmd_keyword", "keyword help", value, optional=True)
            self.next_is(cmd_keyword_node, optional=True)
            self.next_is(cmd_keyword_node, value_node, optional=True)
        '''
        assert not self.is_terminal_node()

        # Parse argument list to get keyword, keyword_help and value
        assert len(args) > 0 and len(args) < 4
        keyword = args[0]
        keyword_help = None
        value = None
        if isinstance(keyword, Keyword):
            if len(args) == 2:
                assert isinstance(args[1], ValueNode)
                value = args[1]
            else:
                assert len(args) == 1
            # Copy keyword content. We don't re-use the keyword node
            keyword = keyword.keyword()
            keyword_help = keyword.help_string
        else:
            if len(args) > 1 and isinstance(args[1], str):
                keyword_help = args[1]
            if len(args) == 2 and isinstance(args[1], ValueNode):
                value = args[1]
            elif len(args) == 3:
                assert isinstance(args[2], ValueNode)
                value = args[2]

        is_merge = kwargs.get("merge", False)
        optional = kwargs.get("optional", False) if kwargs else False

        if value:
            # Must be a fresh value node
            assert value.parent_node is None and not value.child_nodes

        # Registered command is frozen and cannot accept new args
        command = self.get_root()
        assert not command.is_registered()

        has_binding = command.value_binding(keyword)
        if has_binding is not None:
            if has_binding is True and not value:
                raise PathException(
                    "%s is a value key. Must be followed by a value" % keyword)
            if has_binding is False and value:
                raise PathException(
                    "%s is not a value key. Cannot be followed by a value" % (
                        keyword))

        # Terminate all other child nodes if not yet
        for c in self.child_nodes:
            if c.is_terminal_node():
                continue
            c.terminate_paths()

        # Check conflict in child nodes.
        for c in self.child_nodes:
            if c.is_terminal_node():
                continue
            assert c.is_keyword()
            if c.keyword() == keyword:
                if not is_merge:
                    raise PathException("%s already defined in %s" % (
                        keyword, self.path_string()))
                if optional != c.is_optional():
                    raise PathException("%s inconsistent optional flag: %s" % (
                        keyword, self.path_string()))
                # For merge the value node must be the same for a keyword
                if has_binding is True:
                    child_value = c.child_nodes[0]
                    if not child_value.name() == value.name():
                        raise PathException("Conflict in value node %s: %s" % (
                            child_value.name(), value.name()))
                    return child_value
                return c

        # Add the new node(s)
        keyword_node = Keyword(keyword, help_string=keyword_help,
                               optional=optional)
        if value:
            keyword_node.child_nodes.append(value)
            value.parent_node = keyword_node

        self.child_nodes.append(keyword_node)
        keyword_node.parent_node = self
        if has_binding is None:
            command.set_value_binding(keyword, value is not None)

        return keyword_node if not value else value

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
            for c in node.child_nodes:
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
        for c in self.child_nodes:
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
                    if self.get_root().discard_trailing_tokens:
                        return True
                    raise PathException("Unmatched trailing tokens: %s" % (
                        tokens[1:]))
                elif c.walk(tokens, pos + 1):
                    return True
            if c.is_optional():
                assert c.is_keyword()
                # Skip the value node
                r = c.value_child().walk(tokens, pos)
                if r:
                    return True
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

    def __init__(self, keyword, help_string=None):
        Keyword.__init__(self, keyword, help_string=help_string)
        # Command keyword always followed by a keyword
        self.keyword_value_binding = { keyword : False }
        self.discard_trailing_tokens = False
        self.context_name = None

    def value_binding(self, keyword):
        if not keyword in self.keyword_value_binding:
            return None
        return self.keyword_value_binding[keyword]

    def set_value_binding(self, keyword, is_value):
        assert keyword not in self.keyword_value_binding
        self.keyword_value_binding[keyword] = is_value

    def is_registered(self):
        return self.context_name is not None

    def check_paths(self):
        collect_terminal_nodes = []
        self.terminate_paths(collect_terminal_nodes)
        # Collect all potential paths and check if any conflict
        all_paths = []
        for node in collect_terminal_nodes:
            paths = node.collect_paths()
            all_paths.extend(paths)
        print("Total number of paths %d" % len(all_paths))
        all_path_strs = set([])
        duplicate_paths = []
        for p in all_paths:
            s = "/".join("%s" % n.name for n in p)
            if s in all_path_strs:
                duplicate_paths.append(s)
            else:
                all_path_strs.add(s)
        if duplicate_paths:
            print("Duplicate paths found:")
            for p in duplicate_paths:
                print("    " + p)
            raise PathException("Failed to register command %s" % self.name)

    def merge(self, new_node_chain):
        '''
        Merge a newly created cmd node chain into existing (registered)
        cmd node tree
        '''
        assert isinstance(new_node_chain, Command) and \
            self.keyword() == new_node_chain.keyword() and \
            not self.is_registered()

        if new_node_chain.is_leaf():
            return self

        new_node = new_node_chain.child_nodes[0]
        current_node = self

        def is_kv(node):
            # node is a keyword binding with a value node
            assert node.is_keyword()
            return not node.is_leaf() and node.child_nodes[0].is_value()

        current_node = None
        while new_node:
            optional = new_node.is_optional()
            if is_kv(new_node):
                node = current_node.next_is(new_node,
                                            new_node.child_nodes[0],
                                            optional=optional,
                                            merge=True)
                if not node:
                    return None
                if new_node.child_nodes[0].is_leaf():
                    return node
                current_node = node
                new_node = new_node.child_nodes[0].child_nodes[0]
            else:
                node = current_node.next_is(new_node,
                                            optional=optional,
                                            merge=True)
                if not node:
                    return None
                if new_node.is_leaf():
                    return node
                current_node = node
                new_node = new_node.child_nodes[0]
        return current_node

    def dump_commands(self):
        self.dump_node()

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
    context_name = args[0] if len(args) == 2 else global_context_name
    value_node = args[0] if len(args) == 1 else args[1]
    assert isinstance(value_node, ValueNode)
    if context_name not in registered_values:
        registered_values[context_name] = { value_node.name : value_node }
        return
    assert value_node.name not in registered_values[context_name]
    registered_values[context_name][value_node.name] = value_node

def get_value_of_token(context_name, token):
    if context_name in registered_values:
        if token in registered_values[context_name]:
            return registered_values[context_name][token]
    return registered_values[global_context_name].get(token, None)

def parse_cmd_spec_string(context_name, cmd_str):
    '''
    Parser a command spec string. Return a chain of nodes, with the first
    node being a Command node.
    '''
    tokens = tokenize_cmd_spec_string(cmd_str)
    cmd = tokens.pop(0)
    if not is_keyword_str(cmd):
        raise ParseException("Invalid command string %s" % cmd)
    if cmd in registered_commands[context_name]:
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
            if not tokens or not is_value_token(token[0]):
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
            optional = True
        elif token == "]":
            if not optional:
                raise ParseException("Unbalanced optional bracket")
            optional = False
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
    registered_commands[context_name] = (cmd_node, handler)
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

    if len(args) == 1:
        return register_command(args[0],
                                global_context_name,
                                default_command_handler)
    if len(args) == 2:
        if isinstance(args[1], str):
            return register_command(args[0], args[1], default_command_handler)
        return register_command(args[0], global_context_name, args[1])

    # len(args) == 3
    if isinstance(args[0], str):
        return register_command([args[0]], args[1], args[2])
    if isinstance(args[0], Command):
        return register_command_node(args[0], args[1], args[2])

    assert isinstance(args[0], list)

    new_commands = {}
    context_name = args[1] if len(args) == 3 else global_context_name
    handler = args[1] if len(args) == 2 else args[2]

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
        n = register_command(cmd_node, context_name, handler)
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
