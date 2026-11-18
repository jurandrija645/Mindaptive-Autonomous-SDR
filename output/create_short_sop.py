from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle

OUT = 'output/Deal_Flow_Lead_Research_SOP_Short.pdf'
pdfmetrics.registerFont(TTFont('Arial', 'C:/Windows/Fonts/arial.ttf'))
pdfmetrics.registerFont(TTFont('ArialBold', 'C:/Windows/Fonts/arialbd.ttf'))
pdfmetrics.registerFontFamily('Arial', normal='Arial', bold='ArialBold')
c = canvas.Canvas(OUT, pagesize=A4)
W,H = A4
blue=HexColor('#183c5b'); ink=HexColor('#1f2937'); muted=HexColor('#596878')
body=ParagraphStyle('body',fontName='Arial',fontSize=9.3,leading=13.4,textColor=ink,spaceAfter=0)
head=ParagraphStyle('head',fontName='ArialBold',fontSize=11,leading=14,textColor=blue)
small=ParagraphStyle('small',fontName='Arial',fontSize=8.5,leading=12,textColor=ink)
def para(t,y,style=body):
    p=Paragraph(t,style); _,h=p.wrap(W-90,800); p.drawOn(c,45,y-h); return y-h
def title(title,sub):
    c.setFillColor(blue); c.setFont('ArialBold',20); c.drawString(45,H-54,title)
    c.setFont('Arial',9); c.setFillColor(muted); c.drawString(45,H-72,sub)
    c.setStrokeColor(HexColor('#d9e2ea')); c.line(45,H-82,W-45,H-82)
    return H-100
def section(t,y):
    y=para(t,y,head); return y-6
def item(label,txt,y):
    y=para('<b>'+label+'</b> '+txt,y); return y-7
def footer(n):
    c.setStrokeColor(HexColor('#d9e2ea')); c.line(45,38,W-45,38)
    c.setFont('Arial',8); c.setFillColor(muted); c.drawString(45,25,'DEAL FLOW  /  LEAD RESEARCH'); c.drawRightString(W-45,25,str(n)+' / 2')

y=title('Lead Research SOP','Short operating guide  |  November 2026')
y=para('The Lead Research Specialist builds and personalizes a checked lead list for each student campaign. The Outreach Specialist owns the pitch, import, sequences and sending.',y); y-=13
y=section('1  Define and source',y)
y=item('Brief first.', 'Record the target brand, student’s shipping or location condition, exclusions, segment or tier, market, target size and whether fallback roles are allowed. Resolve missing answers with Outreach or the Coach before searching.',y)
y=item('Build the pool.', 'Use Saleshandy Lead Finder with the approved role, industry and market filters. Keep searches within its 100-result view, verify saved filters and turn on Exclude Existing Prospects. Use Apollo with the same filters when Lead Finder runs dry. Aim for a raw pool 4–5 times the target; agree a smaller target if needed.',y)
y=section('2  Qualify brands and people',y)
y=item('Check every brand.', 'Use its own website to confirm it sells its own products or runs its own venue, fits the niche and is not excluded. Recheck unclear cases; remove them if still uncertain. Confirm shipping to the student’s country or a suitable venue location, and assign the agreed tier or segment.',y)
y=item('Choose decision-makers.', 'Prioritize creator, influencer or partnerships roles; then marketing; brand, social, content or PR; then founder or owner. Use GM or PR Manager as a fallback only when the brief allows it and no higher-priority role exists. For large brands, choose the student’s regional team.',y)
y=item('Limit and flag.', 'Select up to four people per brand, best role first. Flag brands with multiple contacts so Outreach can space sends. Use people returned by the approved searches; get written approval for wider searches or roles outside the SOP and log it.',y)
y=section('3  Verify and audit',y)
y=item('Emails.', 'Reveal work emails in budgeted rounds and log found, valid and credits used. Keep only verified <b>valid</b> addresses; exclude risky, catch-all, bad, personal and generic inboxes.',y)
y=item('Every row.', 'Remove duplicates and existing prospects. Check first name, decision-making role, region, segment and email domain. A parent-company domain is acceptable; an unrelated domain is not. For chain venues, deduplicate by name and domain together. Maximum: 700 leads per campaign.',y)
assert y>45, y
footer(1); c.showPage()
y=title('Personalize & hand over','Final checks before import')
y=section('4  Fill the fields',y)
y=item('Read the pitch first.', 'Identify each variable, the sentence it appears in and its fallback. Check every filled value in that actual sentence.',y)
y=item('Company Short.', 'Fill every row with a natural brand name. Remove legal endings, slogans and unnecessary location or category text; preserve the brand’s spelling. Use the original name if needed.',y)
y=item('Product / Experience.', 'Use a real, concise product or experience from the brand’s own site that fits the student’s video idea. Use the same answer for everyone at the same brand. Leave it blank when unsure so the pitch fallback is used. Never guess.',y)
y=item('Recent Content.', 'Where the pitch uses it, include only a true observation; otherwise leave that line out. Review three random previews aloud for broken variables or unnatural wording.',y)
y=section('5  Quality check and delivery',y)
y=item('Five gates.', 'Every lead must have: a fitting brand; a brand able to work with the student; a decision-maker in the right region; a valid work email; and truthful personalization or a safe fallback.',y)
y=item('Independent spot check.', 'The Outreach Specialist checks 20 random rows from scratch against all five gates. One failure: check 50 more rows. Two failures: redo the failed step across the whole list. Hold the handover until checks pass.',y)
y=item('Save both files.', 'Final CSV: C&lt;n&gt;_FINAL_EMAILS_&lt;student&gt;.csv, with first name, last name, email, job title, company, domain, city, segment/tier and LinkedIn URL. Save personalization separately as C&lt;n&gt;_&lt;student&gt;_personalized.csv. Do not overwrite or delete lead files.',y)
y=item('Log and hand over.', 'Record firms seen and kept, brands with people, people chosen, emails revealed and valid, audit removals, final count, credits, exceptions and field fill rates. Give Outreach both CSVs and the log. Lead data stays in agreed files, never in documents, chats or Slack.',y)
y=section('Planning & role',y)
y=para('Prepare the next list before the current campaign ends. At 40–45 emails per day, with one pitch and one follow-up per lead, a 700-lead campaign lasts about a month. Priorities and credit budgets are agreed with Outreach and the Head of Product.',y); y-=7
y=para('The role requires strong written English, sound brand and contact research judgment, experience with lead databases, spreadsheet skills and careful data handling. A paid trial checks 150 firms and 30 contacts; pass at least 92% correct “in” brands, with no invented products.',y,small)
assert y>45, y
footer(2); c.save()
print(OUT, 'bottom', y)
