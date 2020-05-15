
import re
import shlex

NodeId  = 0

def GenerateId():
    NodeId += 1
    return NodeId

class PathException(Exception):
    pass

        
class Node:
    def __init__(self, name, help=None, optional=False):
        self.__name = name
        self.__help = help
        self.__paths = [] # in order of addition
        self.__previous = None
        self.__optional = optional

    def name(self):
        return self.__nodeId
        
    def previous(self):
        return self.__previous

    def help_string(self):
        return self.__help
        
    def paths(self):
        return self.__paths

    def is_keyword(self):
        return False

    def is_numerical(self):
        return False

    def is_numerical_range(self):
        return False

    def is_selective(self):
        return False

    def is_literal(self):
        return False

    def is_optional(self):
        return __is_optional

    def path_string(self):
        if not self.__previous:
            return self.__name
        return self.__previous.path_string() + "/" + self.__name
        
    def can_consume(self, a_str):
        raise NotImplementedError()

    def consume(self, a_str):
        raise NotImplementedError()
        
    def complete(self, aStr):
        '''
        Subclass returns a list of tuples (<value>, <description>), e.g.
        self.complete("emp") would return:
        [("employee-name", "Employee name"),
         ("employee-number", "Employee number"),
         ("employee-location", "Employee office location")]
        '''
        raise NotImplementedError()
        
    def next_is(self, next_node):
        '''Add a new node to child tokens'''
        assert next_node.previous() is None
        if next_node.name() in self.__paths:
            printError("Token name %s already in path" % next_node.name())
            return None
        for node in self.__paths:
            if node.has_sibling_conflict(next_node):
                return None
        if self.isOptional():
            # If this node is optional look back the path and check if there
            # is any potential conflict
            prev = self.__previous
            while prev:
                for node in prev.paths():
                    if node.nodeId() == self.__nodeId
                        continue # skip self
                    if node.has_sibling_conflict(next_node):
                        return None
                if prev.is_optional():
                    prev = prev.previous()
                else:
                    break
        self.__paths.append(next_node)
        next_node.set_previous(self)
        return next_node

    def has_sibling_conflict(self, new_node):
        '''
        Check if this node has conflict with a new_node, when the new_node is to
        be added as a sibling of this node
        '''
        if self.is_literal() or new_node.is_literal():
            print_error("Literal node %s cannot have literal silbing %s" % (
                self.path_string(), new_node.name()))
            return True
        elif self.is_keyword():
            if new_node.is_keyword():
                if self.keyword() == new_node.keyword():
                    printError("Keyword already exists: %s for path %s" % (
                        self.keyword(), self.path_string()))
                    return True
            elif new_node.is_numerical() or new_node.is_numerical_range():
                # numerical/range can follow a keyword
                pass
            else:
                assert new_node.is_selective()
                if new_node.can_consume(self.keyword()):
                    printError("Node %s can consume keyword %s" % (
                        new_node.name(), self.keyword()))
                    return True
        elif self.is_numerical() or self.is_numerical_range():
            if new_node.is_numerical() or new_node.is_numerical_range():
                printError("Numerical node %s cannot have sibling %s" % (
                    self.path_string(), new_node.name()))
                return True
        elif self.is_selective():
            if new_node.is_keyword():
                if self.can_consume(new_node.keyword()):
                    printError("Node %s can consume %s" % (
                        self.path_string(), new_node.name()))
                    return True
            elif new_node.is_numerical() or new_node.is_numerical_range():
                print_error("Selective %s cannot have numerical sibling %s" % (
                    self.path_string(), new_node.name()))
                return True
            else:
                assert new_node.is_selective()
                pfx = self.prefix()
                newPfx = new_node.prefix()
                if pfx is None or newPfx is None:
                    print_error("Selective %s cannot have selective sibling %s" % (
                        self.path_string(), new_node.name()))
                    return True
                elif pfx.startswith(pfx2) or pfx2.startswith(pfx):
                    print_error("Selective %s prefix %s overlaps %s prefix %s" % (
                        self.path_string(), pfx, new_node.name(), pfx2))
                    return True
        if self.is_optional():
            for node in self.__paths:
                if node.has_sibling_conflict(new_node):
                    return True
        return False

    def evaluate(context, tokens, run=False):
        '''
        Evaluate command.
        @context is the context the command is entered into
        @tokens is the list of tokens entered
        '''
        # A command node must be the top node in node chain
        assert self.is_top_node()
        walk_result = []
        for node in self.__paths:
            result = {}
            try:
                if node.walk(context, tokens, 1, result):
                    walk_result.append(result)
            except PathException as pe:
                print_error(pe)
                return None
        if len(walk_result) == 0:
            return None
        if len(walk_result) > 1:
            print_error("Multiple paths possible for %s: %s" % (
                tokens, walk_result))
            return None
        if run:
            if self.__handler:
                return self.__handler(context, tokens, walk_result[0])
            # Handler not installed. Default is to print a string
            print("Evaluate successful: " + str(walk_result[0]))
        return values

    def walk(self, context, tokens, start_pos, result):
        '''Walk the node'''
        token = tokens[start_pos]
        r = self.consume(token)
        if not r:
            if self.__is_optional and self.__next:
                return self.__next.walk(context, tokens, start_pos, result)
            return None
        result[self.name()] = r
        if not self.__next:
            return r
            
        # walk down the path
        r = self.__next.walk(context, tokens, start_pos + 1, result)
        if not r:
            return None

        # walk is successful. make sure there is no alternative path
        if self.__is_optional:
            alt_r = self.__next.walk(context, tokens, start_pos, result)
            if alt_r:
                throw PathException("Ambiguous path detected %s" % tokens)
        return r
        
        
class Keyword(Node):
    def __init__(self, keyword, **kwargs):
        Node.__init__(self, keyword, **kwargs)
        self.__keyword = keyword

    def keyword(self):
        return self.__keyword

    def is_keyword(self):
        return True

    def can_consume(self, a_str):
        return self.__keyword.startswith(a_str)

    def consume(self, a_str):
        if self.__keyword == a_str:
            return self.__keyword
        return None
        
    def complete(self, a_str):
        if self.__keyword.startswith(a_str):
            return [(self.__keyword, self.help_string())]
        return []

class Numerical(Node):
    def __init__(self, name, num_type, value, **kwargs):
        if not num_type in ["integer", "float"]:
            raise TypeError(num_type)
        Node.__init__(self, name, **kwargs)
        self.__numType = num_type
        try:
            if num_type == "integer":
                self.__value = int(value)
            elif num_type == "float":
                self.__value = float(value)
        except Exception:
            raise ValueError(value)

    def is_numerical(self):
        return True
        
    def can_consume(self, a_str):
        try:
            if self.__num_type == "integer":
                v = int(a_str)
            elif self.__num_type == "float":
                v = float(a_str)
            return True
        except Exception:
            return False

    def consume(self, a_str):
        try:
            if self.__num_type == "integer":
                return self.__value if self.__value == int(a_str) else None
            elif self.__num_type == "float":
                return self.__value if self.__value == float(a_str) else None
        except Exception:
            return None
        
    def complete(self, a_str):
        if str(self.__value.startswith(a_str)):
            return [(str(self.__value), self.help_string())]
        return None
                
class NumericalRange(Node):
    def __init__(self, name, low, hi, num_type, **kwargs):
        if not num_type in ["integer", "float"]:
            raise TypeError(num_type)
        Node.__init__(self, name, kwargs)
        self.__numType = num_type        
        try:
            if self.__num_type == "integer":
                self.__low = int(low)
                self.__hi = int(hi)
            elif self.__num_type == "float":
                self.__low = float(low)
                self.__hi = float(hi)
        except Exception:
            raise ValueError()

    def is_numerical_range(self):
        return True

    def can_consume(self, aStr):
        try:
            v = int(aStr)
            return self.__low <= v and self.__hi >= v
        except Exception:
            return False

    def complete(self, aStr):
        return [(None, self.helpStr())]

class Literal(Node):
    '''Literal is typed entity. Subclass implements more specific logic'''
    def __init__(self, name, **kwargs):
        Node.__init__(self, name, kwargs)

    def is_literal(self):
        return True

    def can_consume(self, a_str):
        # Base class only implements default behavior
        m = re.match(r"[a-zA-Z_-]+", a_str)
        return m is not None

    def consume(self, a_str):
        m = re.match(r"[a-zA-Z_-]+", a_str)
        return a_str if m else None
            
    def complete(self, a_str):
        return [("", self.help_string())]

class Selective(Node):
    '''Base class for selective token'''
    def __init__(self, name, choices=None, **kwargs):
        Node.__init__(self, name, kwargs)
        # A choice must be a tuple of (str, help)
        self.__choices = choices

    def is_selective(self):
        return True

    def can_consume(self, a_str):
        if not self.__choices:
            return False
        for item in self.__choices:
            if item[0].startswith(a_str):
                return True
        return False

    def consume(self, a_str):
        if not self.__choices:
            return None
        for item in self.__choices:
            if item[0] == a_str:
                return item[0]
        return None
            
    def complete(self, a_str):
        if not self.__choices:
            return None
        choices = []
        for item in self.__choices:
            if item[0].startswith(a_str):
                choices.append(item)
        return choices if choices else None

#--------------------------------
# Context
#--------------------------------
    
class Context:

    def __init__(self):
        self.__prev = None
        self.__next = None
        
    def prompt(self):
        pass

    def on_enter(self, **kwargs):
        pass
        
    def on_exit(self, **kwargs):
        pass
        
    def push_context(self, new_context):
        assert self.__mode != new_context.mode() and \
               self.__next is None and new_context.prev() is None
        self.__next = new_context
        new_context.set_previous(self)
        return new_context

    def pop_context(self):
        self.__next = None

    def set_previous(self, parent_conext):
        assert self.__prev = None
        self.__prev = parent_conext

    def exit(self):
        # Must be the bottom context
        assert self.__next == None
        self.on_exit()
        if self.__prev is not None:
            self.__prev.pop_context()

    def evaluate_command(self, cmd_str, run=False):
        if self.__next is not None:
            return self.__next.evaluate_command(cmd_str, run=run)
        cmd_and_args = shlex.split(cmd_str)
        cmd = cmd_and_args.pop(0)
        if not cmd in self.__commands:
            print_error("Invalid command %s in context %s" % (
                cmd, self.context_str()))
            return None
        return self.__commands[cmd].execute(self, cmd_and_args, run=run)
        
class ExecContext(Context):
    '''Top-level execution context'''
    def __init__(self):
        Context.__init__(self)

    def prompt(self):
        return "#"

    def on_exit(self):
        pass

    
#--------------------------------
# RunTime
#--------------------------------
class RunTime:
    def __init__(self, context):
        self.__context = context

    def complete_command(self, cmd_str):
        return self.__context.completeCommand(cmd_str)
        tokens = shlex.split(aStr)
        for cmd in self.__commands:
            if cmd.keyword() != tokens[0]:
                continue
            result = cmd.walk(tokens, action="complete")
            if result:
                return result

    def parse_command(self, cmd_str, run=False):
        return self.__context.parse_command(cmd_str, run=run)

    def run_command(self, cmd_str):
        return self.__context.parse_command(cmd_str, run=True)
        
        tokens = shlex.split(aStr)
        for cmd in self.__commands:
            if cmd.keyword() != tokens[0]:
                break
            if cmd.walk(tokens, action="execute")
                break

