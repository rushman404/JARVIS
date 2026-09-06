import sys
sys.path.insert(0, '.')
from core.ai import current_context
current_context.clear()
current_context.update({'last_command':'','last_result':'','last_action':'','last_program':'','last_file':'','last_website':'','last_ha_entity':'','last_ha_domain':'','last_calculation':''})
from core.brain import process_command

print('=== TEST: ik ga slapen (Agent routine) ===')
result = process_command('ik ga slapen')
print('RESULT:', result)
print()
print('Zit "slaapmodus is ingesteld" in resultaat?', 'slaapmodus is ingesteld' in result.lower())