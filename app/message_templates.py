"""Seed content for the editable message templates (db.message_templates).

These used to live as a hardcoded MESSAGE_TEMPLATES constant in app/static/app.js,
which meant changing a template's wording needed a commit and a deploy. They now
live in SQLite and are edited from the "Message templates" modal — this list is
only used to populate the table the first time it's created (see db.init_db), so
editing it here has no effect on an existing database.

`{name}` and `{company}` are placeholders filled in client-side (app.js
quickFollowup) from the lead's name/company right before the text is posted to
/quick-draft. Keep them spelled exactly like that.
"""

DEFAULT_TEMPLATES: list[dict] = [
    {
        "label": "Prototype offer (already-built agent)",
        "text": "Hi {name},\n\nI actually went ahead and created a prototype Ai Agent for {company}. It's trained on your website data. Wanted to provide some value upfront because I know that's how you get ahead in this industry. Would love to show you how it works over a call -> https://calendly.com/andrew-mindaptive/30min\n\nYours to keep regardless.\n\nAndrew",
    },
    {"label": "", "text": "Wanted to make sure you saw this, let me know either way"},
    {
        "label": "",
        "text": "Hey {name}, I'm locking in projects for next week, let me know if you'd like to move forward or if the timing changed",
    },
    {"label": "", "text": "{name} - just bumping this up in case it got buried. No rush at all"},
    {
        "label": "",
        "text": "Hey {name}, just checking in on this. Let me know if there's anything I can help clarify.",
    },
    {
        "label": "",
        "text": "Hi {name}, closing this file, it seems that now is not the right time. No worries though, it happens. Wishing you and your company all the best.",
    },
    {"label": "", "text": "{name} - please give me your thoughts on this"},
]
