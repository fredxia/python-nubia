#!/usr/bin/python3

import os, sys
import pdb

script_dir = os.path.dirname(__file__)
if not script_dir.startswith("/"):
    script_dir = os.getcwd() + "/" + script_dir
sys.path.append(script_dir)

from rule_parser import Keyword, Value, Context, IntValue, IntRange, RunTime, Command

class MyContext(Context):
    def __init__(self):
        Context.__init__(self, "my_context")

my_context = MyContext()

cmd = Command("my_cmd", "My command")
cmd.next_arg_is("cmd1", IntValue("my_int_value"))
cmd.next_keyword_is("cmd2").next_keyword_is("cmd3", optional=True)

rangeValue = IntRange("range1", 10, 20, help_string="Range1 help")
value_node = cmd.get_path("my_cmd/cmd1/my_int_value")
value_node.next_keyword_is("end_cmd")

value_node.next_arg_is(
    "cmd9", rangeValue, help_string="Cmd2 help", optional=True).\
    next_keyword_is("cmd4", help_string="End at cmd4")

rangeValue2 = IntRange("range2", 10, 20, help_string="Range2 help")
value_node.next_args_are([("cmd4", "Cmd4 help"),
                          ("cmd5", "Cmd5 help", rangeValue2)])

#value_node.next_arg_is("cmd5", IntValue("value2"), optional=True).next_is("cmd4")

def my_command_handler(cmd_context, tokens, values):
    print("%s calling my_command_handler, tokens %s, values %s" % (
        cmd_context.name, tokens, values))

my_context.register_command(cmd, my_command_handler, discard_trailing_tokens=False)

cmd, _ = my_context.get_command("my_cmd")
cmd.print_commands()

run_time = RunTime("runtime", my_context)
run_time.evaluate_command("my_cmd cmd1 2")
run_time.evaluate_command("my_cmd cmd2 cmd3")
run_time.evaluate_command("my_cmd cmd2")
run_time.evaluate_command("my_cmd cmd1 2 end_cmd")
run_time.evaluate_command("my_cmd cmd1 2 cmd3 10 cmd4")
run_time.evaluate_command("my_cmd cmd1 2 cmd4")
