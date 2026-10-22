// n8n Code node, run once for all items. Keep the embedded workflow copy in sync.
const approvedCodes = new Set(['VIP8401', 'OBLACCESS55', 'OBLACCESS25']);
const labels = ['Client Name', 'Email', 'Discount Code', 'Discount Code Value',
  'Location', 'Date', 'Time', 'Appointment Date', 'Appointment Time'];
const results = [];

for (const [index, item] of $input.all().entries()) {
  const message = item.json;
  const body = typeof message.body === 'string' ? message.body : message.body?.content;
  if (!body) throw new Error('Booking email has no full body; use Raw Outlook output.');
  const text = body.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '')
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, '')
    .replace(/<[^>]+>/g, '\n')
    .replace(/&#(x[\da-f]+|\d+);/gi, (_, code) => String.fromCodePoint(
      code[0].toLowerCase() === 'x' ? parseInt(code.slice(1), 16) : parseInt(code, 10)))
    .replace(/&nbsp;/gi, ' ').replace(/&amp;/gi, '&')
    .replace(/&lt;/gi, '<').replace(/&gt;/gi, '>')
    .replace(/&quot;/gi, '"').replace(/&apos;/gi, "'")
    .replace(/\r\n?/g, '\n').replace(/\n[ \t]*:[ \t]*\n/g, ':\n');
  const lines = text.split('\n').map(line => line.trim()).filter(Boolean);
  const isLabel = line => labels.some(label =>
    new RegExp('^' + label + '[ \\t]*(?::|$)', 'i').test(line));
  function field(label) {
    const pattern = new RegExp('^' + label + '[ \\t]*(?::[ \\t]*(.*))?$', 'i');
    for (let i = 0; i < lines.length; i++) {
      const match = lines[i].match(pattern);
      if (!match) continue;
      if (match[1]) return match[1].trim();
      const next = lines[i + 1] || '';
      return isLabel(next) ? '' : next;
    }
    return '';
  }
  const code = field('Discount Code').toUpperCase();
  if (!approvedCodes.has(code)) continue;
  const email = field('Email').toLowerCase();
  const name = field('Client Name');
  const validEmail = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
  if (!validEmail && !name) throw new Error('Approved-code booking has no client identity.');
  results.push({json: {
    booking_id: String(message.id || message.internetMessageId || ''),
    email: validEmail ? email : null,
    client_name: name,
    discount_code: code,
    location: field('Location'),
    date: field('Date') || field('Appointment Date'),
    time: field('Time') || field('Appointment Time'),
  }, pairedItem: {item: index}});
}
return results;
