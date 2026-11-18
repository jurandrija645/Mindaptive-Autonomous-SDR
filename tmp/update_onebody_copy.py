from pathlib import Path

root = Path('clients/onebodyldn')
path = root / 'knowledge/response-templates.md'
text = path.read_text(encoding='utf-8')
text = text.replace('Current booking rules (updated 2026-10-22)', 'Current booking rules (updated 2026-10-28)')
text = text.replace('code for the new offer. Keep the £4.99 booking-fee disclosure for physio.',
                    'code for the new offer. Include the £4.99 booking fee that holds the\ntime slot for every offer, including both sports massage options.')
text = text.replace('Andrew approved this booking reply format on 2026-10-22.', 'Andrew updated this booking reply format on 2026-10-28.')
text = text.replace('each person gets one free session.', 'each person at {{company_name}} gets one free session.')
text = text.replace('For massage, use the matching link and template below. Massage booking fees\nhave not been confirmed; do not apply the physio £4.99 fee to massage. Do\nnot send all three links in response to a simple physio yes.',
'''Fill {{company_name}} with the actual company from the lead record or latest
thread/signature. Corrections in the conversation outrank imported data. If
the company cannot be established, use "each person on your team". Never
invent a company or leave the placeholder in a draft.

For massage, use the matching link and template below, including the £4.99
booking fee that holds the time slot, as instructed by Andrew on 2026-10-28.
Do not send all three links in response to a simple physio yes.''')
text = text.replace('clinic the lead\'s own cold email already named — read it from the thread\n(it\'s also in the lead\'s `nearestClinic` custom field if the thread doesn\'t\nhave it) rather than guessing;',
'''clinic most recently agreed in the conversation. A later correction or
rejection outranks the cold email and `nearestClinic` custom field. If no
choice has been made between alternatives, let the lead choose rather than
reusing a rejected clinic;''')
text = text.replace('Use **VIP8401** and choose the clinic that suits you.',
                    "Use **VIP8401** and choose the clinic that suits you. There's a small\n£4.99 booking fee that holds your time slot.")
text = text.replace('Waterloo and West Kensington.\n', "Waterloo and West Kensington. There's a small £4.99 booking fee that holds\nyour time slot.\n")
text = text.replace('listing all ten. Do not invent a massage booking fee or say there is none.',
                    'listing all ten. Always retain the £4.99 booking fee that holds the time slot.')
path.write_text(text, encoding='utf-8')

path = root / 'knowledge/onebody-overview.md'
text = path.read_text(encoding='utf-8')
text = text.replace('Booking the physio offer carries a small', 'Booking any of the three free offers carries a small')
text = text.replace('each person gets one free session.', 'each person at {{company_name}} gets one free session.')
text = text.replace('  Massage booking fees are unconfirmed; do not extrapolate the physio fee.',
'''  Replace {{company_name}} with the real company, taking corrections from the
  latest thread/signature over imported data. If unknown, use "each person on
  your team". Andrew's 2026-10-28 update requires the £4.99 fee disclosure
  for both sports massage offers too: "There's a small £4.99 booking fee
  that holds your time slot."''')
path.write_text(text, encoding='utf-8')
