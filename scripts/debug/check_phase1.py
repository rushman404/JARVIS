import sys
sys.path.insert(0, '.')

# 1. Brain routeert doelen naar Agent, Executor alleen via Agent
from core.brain import process_command
import inspect
src = inspect.getsource(process_command)
print('1. Brain roept Agent aan:', 'agent.run_goal' in src)
print('2. Brain roept Executor NIET direct:', 'execute_action_plan' not in src)

# 2. Agent is bovenop Executor
from core.agent import Agent
src2 = inspect.getsource(Agent._execute_plan)
print('3. Agent gebruikt Executor:', 'execute_action_plan' in src2)

# 3. Standby-scheiding in main.py (exacte anchors)
mainsrc = open('main.py', encoding='utf-8').read()
print('4. main.py STANDBY via ^...$:', r'^ga slapen$' in mainsrc)
print('5. main.py breekt na slaapmodus:', 'slaapmodus is ingesteld' in mainsrc.lower())

# 4. media_stop volledig geintegreerd
from core.agent import VALID_TOOL_NAMES
from core.tools import media_stop_tool
aia = open('core/ai.py', encoding='utf-8').read()
print('6. media_stop in Agent-tools:', 'media_stop' in VALID_TOOL_NAMES)
print('7. media_stop in AI-dispatcher:', 'media_stop' in aia)

# 5. HA alleen bed_lamp in tests
import glob
ha_files = glob.glob('test/*home_assistant*') + glob.glob('test/*entity_resolve*') + glob.glob('test/*ha_match*') + glob.glob('test/*ha_reference*')
other_lights = []
for f in ha_files:
    content = open(f, encoding='utf-8').read()
    if 'eethoek' in content.lower() or 'woonkamer' in content.lower() and 'woonkamer' not in content:
        other_lights.append(f)

non_bed = []
for f in ha_files:
    content = open(f, encoding='utf-8').read()
    # Only flag if a *different* light entity is actively controlled (not just defined in a mock list)
    if ('turn_on' in content or 'turn_off' in content or 'service_data' in content) and 'bed_lamp' not in content:
        non_bed.append(f)

print('8. HA-testbestanden gevonden:', len(ha_files))
print('9. HA-tests die andere lampen BEDIENEN dan bed_lamp:', non_bed if non_bed else 'GEEN')