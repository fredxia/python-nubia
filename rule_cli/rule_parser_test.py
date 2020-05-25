#!/usr/bin/python3

import os, sys
import pdb

script_dir = os.path.dirname(__file__)
if not script_dir.startswith("/"):
    script_dir = os.getcwd() + "/" + script_dir
sys.path.append(script_dir)

from rule_parser import Keyword, ValueNode, IntValue, IntRange, Command, \
    register_keyword, register_value_token, register_command, \
    get_registered_command

# Register command node test
cmd = Command("my_cmd", "My command")
cmd.next_is("cmd1", IntValue("my_int_value"))
cmd.next_is("cmd2", "cmd2 help").next_is("cmd3", optional=True)

value_node = cmd.get_path("my_cmd/cmd1/<my_int_value>")
value_node.next_is("end_cmd1")
value_node.next_is("end_cmd2")

rangeValue = IntRange("range1", 10, 20, help_string="Range1 help")
value_node.next_is("cmd42", "cmd42 help", rangeValue, optional=True).\
    next_is("cmd41", "End at cmd41")

rangeValue2 = IntRange("range2", 10, 20, help_string="Range2 help")
value_node.next_are([("cmd4", "Cmd4 help"),
                     ("cmd14", "Cmd5 help", rangeValue2)])

#value_node.next_keyword_is("cmd41")

#value_node.next_arg_is("cmd5", IntValue("value2"), optional=True).next_is("cmd4")

# Register global context
register_command(cmd)

# Get command
cmd, _ = get_registered_command("my_cmd")
cmd.print_commands()

# Register command spec
register_keyword("acmd1", "help a")
register_value_token(IntValue("my_int", "my int help"))
register_value_token(IntRange("my_range", 10, 20, "my range help"))

register_command("acmd1 <my_int> acmd2")
register_command("acmd3 <my_range> [acmd4 <my_int> acmd5 <my_int>] cmd6",
                 "context2")

cmd, _ = get_registered_command("acmd1")
cmd.print_commands()

cmd, _ = get_registered_command("context2", "acmd3")
cmd.print_commands()
 
# Execute command
#runtime = Runtime("my_runtime")
#runtime.evaluate_command("acmd1 2 acmd2")
