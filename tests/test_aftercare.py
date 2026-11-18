import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app import aftercare, booking_guard, client_assets, db, detector, library, pipeline, scheduler, signatures, smartlead
from app.config import settings


BEFORE = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
INSIDE = datetime(2026, 11, 4, 9, 30, tzinfo=timezone.utc)
END = datetime(2026, 11, 4, 11, tzinfo=timezone.utc)


class AftercareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for obj, name, value in [(settings, 'db_path', str(Path(self.tmp.name)/'test.db')),
                                 (settings, 'dry_run', False),
                                 (settings, 'meeting_booked_category_name', 'Meeting-Booked'),
                                 (client_assets, 'CLIENT_DIR', Path('/clients/onebodyldn'))]:
            p = patch.object(obj, name, value); p.start(); self.addCleanup(p.stop)
        clock = patch.object(aftercare, 'utcnow', return_value=BEFORE)
        clock.start(); self.addCleanup(clock.stop)
        db.init_db()
        self.pdf = Path(self.tmp.name)/'brochure.pdf'; self.pdf.write_bytes(b'%PDF-reviewed')
        self.sha = hashlib.sha256(self.pdf.read_bytes()).hexdigest()
        self.file = dict(slug='one-body-ldn-partnership-brochure.pdf',file_name='brochure.pdf',file_url='https://test.invalid/f/brochure.pdf',file_type='application/pdf',file_size=13)
        with db.db_session() as c:
            db.upsert_lead_state(c,20,10,email='lead@example.com',name='Lead',status='active')
            db.mark_lead_booked(c,20,10)
        self.thread = [detector.NormalizedMessage(kind='reply',timestamp=BEFORE,message_id='last',body='Thanks',from_email='lead@example.com',to_email='kurt@example.com',stats_id='s1'),
                       detector.NormalizedMessage(kind='sent',timestamp=BEFORE,message_id='pinned',body='Hello',from_email='kurt@example.com',to_email='lead@example.com',stats_id='s2')]
        network = patch.object(smartlead,'_request',side_effect=AssertionError('Unexpected network'))
        network.start();self.addCleanup(network.stop)

    def draft(self, approve=True, kind='aftercare'):
        with db.db_session() as c:
            did=db.create_draft(c,lead_id=20,campaign_id=10,kind=kind,status='scheduled',
                scheduled_at='2026-11-04T09:30:00+00:00',body_html='<p>How was your session?</p>',
                signature_html='<table>Kurt Johnson</table>',sender_email='kurt@example.com',
                lead_email='lead@example.com',to_override='lead@example.com',cc_override='',
                attachments=json.dumps([self.file]),reply_message_id='pinned',reply_stats_id='s2',reply_email_time=BEFORE.isoformat())
            if approve:
                aftercare.authorize(c,did,starts_at='2026-11-04T09:00:00+00:00',expires_at='2026-11-04T11:00:00+00:00',approved_by='Mia: exact message and PDF',attachment_sha256=self.sha)
            return dict(db.get_draft(c,did))

    def live(self, draft, *, categories=None, mappings=None):
        mappings=mappings or [dict(email_campaign_id='10',lead_category_id=7,is_active=True,status='PAUSED')]
        with patch.object(smartlead,'get_lead_campaign_overview',return_value={'email_campaign_leads_mappings':mappings}), patch.object(
            smartlead,'fetch_categories',return_value=categories or {'Meeting-Booked':7}), patch.object(
            library,'resolve',return_value=(self.pdf,'application/pdf','brochure.pdf')), patch.object(aftercare,'utcnow',return_value=INSIDE):
            return aftercare.allow_send(draft,self.thread)

    def test_authorized_queue_survives_booking_freeze_but_regular_outreach_does_not(self):
        care=self.draft();outreach=self.draft(approve=False,kind='followup')
        with db.db_session() as c:
            db.mark_lead_booked(c,20,10)
            self.assertEqual(db.get_draft(c,care['id'])['status'],'scheduled')
            self.assertEqual(db.get_draft(c,outreach['id'])['status'],'stale')
            self.assertEqual(db.get_lead_state(c,20,10)['status'],'booked')
        self.assertFalse(booking_guard.allow_send(20,10))

    def test_exact_window_starts_at_nine_and_expires_at_eleven(self):
        d=self.draft()
        with db.db_session() as c:
            self.assertIsNone(aftercare.approval_for(c,d,for_send=True,now=BEFORE))
            self.assertIsNotNone(aftercare.approval_for(c,d,for_send=True,now=INSIDE))
            self.assertIsNone(aftercare.approval_for(c,d,for_send=True,now=END))
        with patch.object(aftercare,'utcnow',return_value=END), db.db_session() as c:
            db.mark_lead_booked(c,20,10)
            self.assertEqual(db.get_draft(c,d['id'])['status'],'stale')

    def test_editing_body_recipient_pdf_signature_or_schedule_revokes_approval(self):
        for field,value in [('body_html','changed'),('to_override','other@example.com'),('attachments','[]'),('signature_html','different'),('scheduled_at','2026-11-04T10:00:00+00:00')]:
            with self.subTest(field=field):
                d=self.draft()
                with db.db_session() as c:
                    db.update_draft(c,d['id'],**{field:value})
                    self.assertIsNone(aftercare.approval_for(c,d,for_send=True,now=INSIDE))

    def test_no_permission_without_explicit_approval_or_on_other_client(self):
        d=self.draft(approve=False)
        with db.db_session() as c:self.assertIsNone(aftercare.approval_for(c,d,for_send=True,now=INSIDE))
        d=self.draft()
        with patch.object(client_assets,'CLIENT_DIR',Path('/clients/aerodefense')),db.db_session() as c:
            self.assertIsNone(aftercare.approval_for(c,d,for_send=True,now=INSIDE))

    def test_live_booked_status_is_allowed_without_resuming_campaign(self):
        self.assertTrue(self.live(self.draft()))

    def test_pdf_replaced_or_opted_out_mapping_cannot_send(self):
        d=self.draft();self.pdf.write_bytes(b'%PDF-edited')
        self.assertFalse(self.live(d))
        self.pdf.write_bytes(b'%PDF-reviewed')
        self.assertFalse(self.live(d,categories={'Meeting-Booked':7,'Lead Opted Out':8},mappings=[dict(email_campaign_id=10,lead_category_id=7),dict(email_campaign_id=11,lead_category_id=8)]))

    def test_unreadable_remote_status_raises_without_sending(self):
        d=self.draft()
        with patch.object(aftercare,'utcnow',return_value=INSIDE),patch.object(library,'resolve',return_value=(self.pdf,'application/pdf','brochure.pdf')),patch.object(
            smartlead,'get_lead_campaign_overview',side_effect=smartlead.SmartleadError('offline')):
            with self.assertRaises(smartlead.SmartleadError):aftercare.allow_send(d,self.thread)

    def test_changed_thread_or_expired_window_stops_before_send_endpoint(self):
        d=self.draft()
        for now,thread in [(END,self.thread),(INSIDE,self.thread[:1])]:
            with patch.object(aftercare,'utcnow',return_value=now),patch.object(pipeline,'fetch_normalized_thread',return_value=thread),patch.object(smartlead,'reply_to_thread') as send:
                self.assertEqual(scheduler._send_due_draft(d),'stale')
                send.assert_not_called()

    def test_scheduler_sends_only_authorized_care_and_keeps_booked_and_followup_count(self):
        d=self.draft()
        with patch.object(aftercare,'utcnow',return_value=INSIDE),patch.object(pipeline,'fetch_normalized_thread',return_value=self.thread),patch.object(
            signatures,'is_sendable',return_value=True),patch.object(signatures,'get_signature_html',return_value=d['signature_html']),patch.object(
            aftercare,'allow_send',return_value=True),patch.object(smartlead,'reply_to_thread',return_value='queued') as send:
            self.assertEqual(scheduler._send_due_draft(d),'sent')
        self.assertEqual(send.call_count,1)
        self.assertEqual(send.call_args.kwargs['attachments'],[self.file])
        self.assertEqual(send.call_args.args[1].count(d['signature_html']),1)
        with db.db_session() as c:
            s=db.get_lead_state(c,20,10)
            self.assertEqual(s['status'],'booked');self.assertEqual(s['category'],'booked');self.assertEqual(s['followup_count'],0)


if __name__=='__main__':unittest.main()
