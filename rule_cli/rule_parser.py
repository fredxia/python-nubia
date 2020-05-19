
import re
import shlex
import pdb

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
    def __init__(self, name, help_string=None, optional=None):
        self.name = name
        self.help_string = help_string
        self.parent_node = None
        self.child_nodes = []
        self.optional = optional
        # Only for root node
        self.keyword_value_binding = None
        self.context = None
        self.discard_trailing_tokens = False
        # Save resolved value during walk
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

    def is_optional(self):
        return self.optional

    def is_registered(self):
        assert self.is_root()
        return self.context is not None

    def get_context(self):
        assert self.is_root()
        return self.context

    def set_context(self, context, discard_trailing_tokens=False):
        assert self.is_root()
        self.context = context
        self.discard_trailing_tokens = discard_trailing_tokens

    def keyword(self):
        assert self.is_keyword()
        return self.name

    def path_string(self):
        if not self.parent_node:
            return self.name
        return self.parent_node.path_string() + "/" + self.name

    def get_path(self, path_string):
        assert self.is_root()
        node_names = path_string.split("/")
        node = self
        while node_names:
            found = False
            name = node_names.pop(0)
            for c in node.child_nodes:
                if c.is_terminal_node():
                    continue
                if c.name() == name:
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

    def print_commands(self):
        assert self.is_root()
        self.print_node()

    def print_node(self, indent=0):
        if self.is_keyword():
            if self.get_root().keyword_value_binding[self.keyword()]:
                value = self.value_child()
                print("%s%s <%s>" % (
                    " " * indent, self.keyword(), value.name()))
                if value.is_terminal_node():
                    print("%s<cr>" % " " * (indent + 4))
                if not value.is_leaf():
                    value.print_node(indent + 4)
            else:
                print("%s%s" % (" " * indent, self.keyword()))
                if self.is_terminal_node():
                    print("%s<cr>" % " " * (indent + 4))
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
            self.get_root().keyword_value_binding[self.keyword()] is True
        for c in self.child_nodes:
            if c.is_value():
                return c
        raise PathException("value child not found")

    def can_terminate_command(self):
        for c in self.child_nodes:
            if c.is_terminal_node():
                return True
        return False

    def next_args_are(self, args, optional=False):
        for arg in args:
            self.next_arg_is(arg[0], help_string=arg[1], optional=optional)

    def next_arg_is(self, keyword, help_string=None, value=None,
                    optional=False):

        assert isinstance(keyword, str)
        assert not self.is_terminal_node()

        if value:
            assert isinstance(value, Node) and \
                value.parent_node is None and not value.child_nodes

        # Registered command is frozen and cannot accept new args
        root = self.get_root()
        assert not root.is_registered()

        if self.is_value():
            if keyword in root.keyword_binding:
                if root.keyword_value_binding[keyword] is True:
                    if not value:
                        raise PathException("%s is a value key" % keyword)
                elif value:
                    raise PathException("%s canont be a value key" % keyword)
        else:
            if root.keyword_value_binding[self.keyword()] is True:
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
            # All must be optional if there are multiple children
            if not c.is_optional() or not optional:
                raise PathException("Cannot add %s to non-optional sibling" % (
                    keyword))

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
        if not keyword in root.keyword_value_binding:
            root.keyword_value_binding[keyword] = value is not None

        return keyword_node if not value else value


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
                values[node.name()] = node.result
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
                    if c.can_terminate_command():
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
    def __init__(self, keyword, help_string, **kwargs):
        Node.__init__(self, keyword, help_string, kwargs)

    def is_keyword(self):
        return True

    def consume(self, a_str):
        if self.keyword() == a_str:
            self.result = self.keyword()
            return True
        return False

class Value(Node):
    def __init__(self, name, help_string, **kwargs):
        Node.__init__(self, name, help_string, kwargs)

    def is_value(self):
        return True

class IntValue(Value):
    def __init_(self, name, help_string, **kwargs):
        super().__init__(self, name, help_string, **kwargs)

    def consume(self, a_str):
        try:
            v = int(a_str)
            self.result = v
            return True
        except ValueError:
            return False

class IntRange(Value):
    def __init__(self, name, help_string, low, high, **kwargs):
        super().__init__(name, help_string, **kwargs)
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
                keyword, self.name()))

        cmd_node.terminate_paths()
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
