
import re
import sys
import shlex
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

# ================================
# Command Node Classes
# ================================

class Node:
    def __init__(self, name, help_string=None, optional=False):
        self.name = name
        self.help_string = help_string
        self.parent_node = None
        self.child_nodes = []
        self.optional = optional
        self.result = None

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

    def terminate_paths(self):
        for c in self.child_nodes:
            if c.is_terminal_node():
                continue
            if c.is_leaf():
                c.child_nodes.append(TerminalNode())
            else:
                c.terminate_paths()

    def clear_result(self):
        self.result = None
        for c in self.child_nodes:
            if c.is_terminal_node():
                continue
            c.clear_result()

    def print_node(self, indent=0):
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

    def next_args_are(self, args, optional=False):
        for arg in args:
            if len(arg) == 2:
                self.next_keyword_is(arg[0], help_string=arg[1], optional=optional)
            else:
                assert len(arg) == 3 and arg[2].is_value()
                self.next_arg_is(arg[0], arg[2], help_string=arg[1],
                                 optional=optional)

    def next_arg_is(self, keyword, value, help_string=None, optional=False):

        assert isinstance(keyword, str)
        assert not self.is_terminal_node()

        if value:
            assert isinstance(value, Node) and \
                value.parent_node is None and not value.child_nodes

        # Registered command is frozen and cannot accept new args
        root = self.get_root()
        assert not root.is_registered()

        binding = root.value_binding(keyword)
        if self.is_value():
            if binding is not None:
                if binding is True:
                    if not value:
                        raise PathException("%s is a value key" % keyword)
                elif value:
                    raise PathException("%s canont be a value key" % keyword)
        else:
            if root.value_binding(self.keyword()) is True:
                raise PathException(
                    "%s is value key. Cannot have more chld node" % (
                        self.path_string()))

        # Check no conflict in child nodes. All child nodes must be keyword
        # nodes at this point
        for c in self.child_nodes:
            if c.is_terminal_node():
                continue
            assert c.is_keyword()
            if c.keyword() == keyword:
                raise PathException("%s already defined in %s" % (
                    keyword, self.path_string()))

        # Terminate all other child nodes if not yet
        for c in self.child_nodes:
            if c.is_terminal_node():
                continue
            c.terminate_paths()

        keyword_node = Keyword(keyword, help_string=help_string,
                               optional=optional)
        if value:
            keyword_node.child_nodes.append(value)
            value.parent_node = keyword_node

        self.child_nodes.append(keyword_node)
        keyword_node.parent_node = self
        if binding is None:
            root.set_value_binding(keyword, value is not None)

        return keyword_node if not value else value

    def next_keyword_is(self, keyword, help_string=None, optional=False):
        return self.next_arg_is(keyword, None, help_string=help_string,
                                optional=optional)
        
    def evaluate(self, tokens):
        assert self.is_root()
        self.clear_result()
        r = self.walk(tokens, 1)
        if not r:
            self.clear_result()
            return None
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
                if c.is_terminal_node():
                    continue
                if c.result is not None:
                    node = c
                    break
        self.clear_result()
        return values

    def walk(self, tokens, pos):
        token = tokens[pos]
        for c in self.child_nodes:
            if c.consume(token):
                if len(tokens) == pos + 1:
                    # All tokens consumed. Abandon if c cannot terminate command
                    if c.may_terminate():
                        return True
                elif c.is_leaf():
                    # more tokens but no child node to walk
                    if self.get_root().discard_trailing_tokens:
                        return True
                elif c.walk(tokens, pos + 1):
                    return True
            elif c.is_optional():
                assert c.is_keyword()
                # Skip the value node
                r = c.value_child().walk(tokens, pos)
                if r:
                    return True
            c.clear_result()
        return False

class TerminalNode(Node):
    def __init__(self):
        Node.__init__(self, "<Terminal>", "")

    def is_terminal_node(self):
        return True

class Keyword(Node):
    def __init__(self, keyword, help_string=None, optional=False):
        Node.__init__(self, keyword, help_string, optional=optional)

    def is_keyword(self):
        return True

    def consume(self, a_str):
        if self.keyword() == a_str:
            self.result = self.keyword()
            return True
        return False

class Command(Keyword):
    def __init__(self, keyword, help_string=None):
        Keyword.__init__(self, keyword, help_string=help_string)
        # Command keyword always followed by a keyword
        self.keyword_value_binding = { keyword : False }
        self.context = None
        self.discard_trailing_tokens = False

    def value_binding(self, keyword):
        if not keyword in self.keyword_value_binding:
            return None
        return self.keyword_value_binding[keyword]

    def set_value_binding(self, keyword, is_value):
        assert keyword not in self.keyword_value_binding
        self.keyword_value_binding[keyword] = is_value

    def get_context(self):
        return self.context

    def set_context(self, context, discard_trailing_tokens=False):
        self.context = context
        self.discard_trailing_tokens = discard_trailing_tokens

    def is_registered(self):
        return self.context is not None

    def check_paths(self):
        self.terminate_paths()

    def print_commands(self):
        self.print_node()
        
class Value(Node):
    def __init__(self, name, help_string=None):
        Node.__init__(self, name, help_string)

    def is_value(self):
        return True

class IntValue(Value):
    def __init_(self, name, help_string=None):
        super().__init__(self, name, help_string)

    def consume(self, a_str):
        try:
            v = int(a_str)
            self.result = v
            return True
        except ValueError:
            return False

class IntRange(Value):
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

# ================================
# Context
# ================================

class Context:
    def __init__(self, name):
        self.name = name
        self.commands = {}
        self.container_context = None
        self.nest_context = None

    def on_enter(self):
        pass

    def on_exit(self, commit=False):
        pass

    def get_prompt(self):
        # pylint: disable=R0201
        return "#"
        # pylint: enable=R0201

    def register_command(self, cmd_node, handler,
                         discard_trailing_tokens=False):

        assert not cmd_node.is_registered()

        keyword = cmd_node.keyword()
        if keyword in self.commands:
            raise PathException("Command %s exists in context %s" % (
                keyword, self.name))

        cmd_node.check_paths()
        cmd_node.set_context(
            self, discard_trailing_tokens=discard_trailing_tokens)
        self.commands[keyword] = (cmd_node, handler)

    def enter_context(self, context):
        assert self.nest_context is None
        self.nest_context = context
        context.container_context = self
        self.nest_context.on_enter()

    def exit_context(self, commit=False):
        if self.nest_context:
            self.nest_context.exit_context(commit)
            self.nest_context = None
        self.on_exit(commit)

    def get_command(self, keyword):
        if keyword in self.commands:
            return self.commands[keyword]
        return None

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
        return self.commands[cmd][1](self, values)

# ================================
# RunTime
# ================================

class RunTime:
    def __init__(self, name, context):
        self.name = name
        self.root_context = context

    def evaluate_command(self, cmd_str):
        return self.current_context().evaluate_command(cmd_str)

    def current_context(self):
        context = self.root_context
        while context.nest_context:
            context = context.nest_context
        return context
