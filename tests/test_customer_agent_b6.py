"""B6: customer-facing agents on shared rails.

- both facades (communication + service desk) write to one interaction log;
- WhatsApp relational copy is refused without consent, transactional copy is
  blocked only by an explicit opt-out;
- the per-customer daily WhatsApp/SMS cap is enforced from the shared log
  (pending rows count);
- OTP verified against the WhatsApp number is captured as consent;
- one escalation path: durable record + audit row + timeline entry;
- the shared TemplateEngine registry serves service-desk templates;
- legacy shims keep their constructor contracts;
- durable in DB mode (agent_artifacts), peer instance sees the rows;
- admin HTTP routes: /interactions (GET) and /consent (POST) are role-scoped.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

import services.hydrated_store as hs
from services.customer_agent import (
    customer_timeline,
    get_consent_registry,
    get_escalation_desk,
    get_interaction_log,
    reset_customer_agent_state,
)
from services.customer_agent.communication import CustomerCommunicationAgent
from services.customer_agent.consent import (
    DAILY_CAP_ENV,
    ENFORCE_ENV,
    MessagingPolicy,
    consent_from_record,
)
from services.customer_agent.interaction_log import mask_recipient
from services.customer_agent.service_desk import (
    SERVICE_TEMPLATES,
    CustomerServiceAgent,
    Delivery,
    ensure_service_templates,
)
from services.notification_service import (
    MockEmailProvider,
    MockSMSProvider,
    NotificationChannel,
    NotificationService,
    OTPRequest,
    TemplateEngine,
    VerificationType,
    create_notification_service,
    reset_global_rate_limiter,
    reset_notification_service,
)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    reset_global_rate_limiter()
    reset_notification_service()
    reset_customer_agent_state()
    monkeypatch.delenv(DAILY_CAP_ENV, raising=False)
    monkeypatch.delenv(ENFORCE_ENV, raising=False)
    yield
    reset_global_rate_limiter()
    reset_notification_service()
    reset_customer_agent_state()


def _comm():
    return CustomerCommunicationAgent(notification_service=create_notification_service(use_mock=True))


CUSTOMERS = {
    'CUST-B6': {'id': 'CUST-B6', 'name': 'Dana Levi', 'email': 'dana@phins.ai', 'phone': '+972501112233'},
    'CUST-NOPHONE': {'id': 'CUST-NOPHONE', 'name': 'Mail Only', 'email': 'mail@phins.ai'},
    'CUST-OPTOUT': {'id': 'CUST-OPTOUT', 'name': 'Opted Out', 'email': 'out@phins.ai',
                    'phone': '+972501119999', 'whatsapp_consent': False},
    'CUST-FLAGGED': {'id': 'CUST-FLAGGED', 'name': 'Flag On Record', 'email': 'flag@phins.ai',
                     'phone': '+972501118888', 'consents': {'whatsapp': True}},
}


def _desk(agent_id='desk-1', **kw):
    return CustomerServiceAgent(
        agent_id, create_notification_service(use_mock=True),
        customer_lookup=CUSTOMERS.get, **kw,
    )


# --------------------------------------------------------------------------
# Shared interaction log
# --------------------------------------------------------------------------

class TestSharedInteractionLog:
    def test_both_facades_write_to_one_log(self):
        comm = _comm()
        desk = _desk()
        welcome = comm.send_welcome_package(
            customer_id='CUST-B6', customer_name='Dana', email='dana@phins.ai',
            whatsapp_phone='+972501112233',
        )
        assert welcome['success'] is True
        inquiry = desk.handle_inquiry('CUST-B6', channel='portal', message='Where is my policy?')
        assert inquiry['acknowledgement'].success is True

        rows = get_interaction_log().for_customer('CUST-B6')
        agents = {r.agent for r in rows}
        assert agents == {'communication', 'service_desk'}
        kinds = [r.kind for r in rows]
        assert kinds.count('welcome') == 2  # email + whatsapp legs
        assert 'inquiry' in kinds
        assert all(r.status == 'sent' for r in rows)
        # The same rows are visible from either facade.
        assert [r.interaction_id for r in comm.interactions_for('CUST-B6')] == \
               [r.interaction_id for r in desk.interactions_for('CUST-B6')]

    def test_rows_are_pending_before_send_and_final_after(self):
        seen = {}

        class Spy(NotificationService):
            def send(self, request):
                row = [r for r in get_interaction_log().for_customer('CUST-B6')][-1]
                seen['status_during_send'] = row.status
                return super().send(request)

        agent = CustomerCommunicationAgent(
            notification_service=Spy(email_provider=MockEmailProvider(), sms_provider=MockSMSProvider()))
        result = agent.send_customer_outreach(
            customer_id='CUST-B6', customer_name='Dana', email='dana@phins.ai',
            template='bill', channels='email', bills=[{'status': 'outstanding', 'amount_due': 10}],
        )
        assert result['success'] is True
        assert seen['status_during_send'] == 'pending'
        row = get_interaction_log().get(result['email']['interaction_id'])
        assert row.status == 'sent'
        assert row.notification_id == result['email']['notification_id']
        assert row.recipient_masked == 'd***@phins.ai'

    def test_send_exception_is_recorded_as_failed_and_reraised(self):
        class Boom(NotificationService):
            def send(self, request):
                raise RuntimeError('provider down')

        agent = CustomerCommunicationAgent(notification_service=Boom())
        with pytest.raises(RuntimeError):
            agent.send_customer_outreach(customer_id='CUST-B6', customer_name='Dana',
                                         email='dana@phins.ai', template='bill', channels='email')
        rows = get_interaction_log().for_customer('CUST-B6')
        assert len(rows) == 1
        assert rows[0].status == 'failed'
        assert rows[0].code == 'SEND_EXCEPTION'

    def test_recipients_are_masked_only(self):
        assert mask_recipient('dana@phins.ai') == 'd***@phins.ai'
        assert mask_recipient('+972501112233') == '***2233'
        assert mask_recipient(None) is None
        _comm().send_customer_outreach(customer_id='CUST-B6', customer_name='Dana',
                                       email='dana@phins.ai', template='bill', channels='email')
        payload = json.dumps([r.to_dict() for r in get_interaction_log().all()])
        assert 'dana@phins.ai' not in payload


# --------------------------------------------------------------------------
# Consent + daily cap
# --------------------------------------------------------------------------

class TestConsentPolicy:
    def test_relational_whatsapp_refused_without_consent(self):
        result = _comm().send_customer_outreach(
            customer_id='CUST-B6', customer_name='Dana', email='dana@phins.ai',
            phone='+972501112233', template='offer', channels='whatsapp',
        )
        assert result['success'] is False
        assert result['code'] == 'CONSENT_REQUIRED'
        assert result['whatsapp']['status'] == 'refused'
        row = get_interaction_log().for_customer('CUST-B6')[-1]
        assert row.status == 'refused' and row.code == 'CONSENT_REQUIRED'
        assert row.metadata['policy']['purpose'] == 'relational'

    def test_transactional_whatsapp_allowed_without_consent(self):
        result = _comm().send_customer_outreach(
            customer_id='CUST-B6', customer_name='Dana', email='dana@phins.ai',
            phone='+972501112233', template='bill', channels='whatsapp',
            bills=[{'status': 'outstanding', 'amount_due': 10}],
        )
        assert result['success'] is True
        assert result['purpose'] == 'transactional'

    def test_explicit_revocation_blocks_even_transactional(self):
        get_consent_registry().set('CUST-B6', 'whatsapp', False, actor='customer')
        result = _comm().send_customer_outreach(
            customer_id='CUST-B6', customer_name='Dana', email='dana@phins.ai',
            phone='+972501112233', template='bill', channels='whatsapp',
        )
        assert result['success'] is False
        assert result['code'] == 'CONSENT_REVOKED'
        welcome = _comm().send_welcome_package(
            customer_id='CUST-B6', customer_name='Dana', email='dana@phins.ai',
            whatsapp_phone='+972501112233',
        )
        assert welcome['email']['success'] is True
        assert welcome['whatsapp']['error_code'] == 'CONSENT_REVOKED'
        assert welcome['success'] is False

    def test_consent_from_customer_record_flags(self):
        assert consent_from_record({'whatsapp_consent': False}, 'whatsapp') is False
        assert consent_from_record({'consents': {'whatsapp': 'yes'}}, 'whatsapp') is True
        assert consent_from_record({'marketing_consent': True}, 'whatsapp', 'relational') is True
        assert consent_from_record({'marketing_consent': True}, 'whatsapp', 'transactional') is None
        assert consent_from_record({}, 'whatsapp') is None

        ok = _comm().send_customer_outreach(
            customer_id='CUST-FLAGGED', customer_name='F', email='flag@phins.ai',
            phone='+972501118888', template='message', channels='whatsapp',
            customer_record=CUSTOMERS['CUST-FLAGGED'],
        )
        assert ok['success'] is True
        assert ok['whatsapp']['success'] is True

        out = _comm().send_customer_outreach(
            customer_id='CUST-OPTOUT', customer_name='O', email='out@phins.ai',
            phone='+972501119999', template='bill', channels='whatsapp',
            customer_record=CUSTOMERS['CUST-OPTOUT'],
        )
        assert out['code'] == 'CONSENT_REVOKED'

    def test_explicit_registry_beats_record_flags(self):
        get_consent_registry().set('CUST-FLAGGED', 'whatsapp', False, actor='customer')
        decision = MessagingPolicy().authorize('CUST-FLAGGED', 'whatsapp', 'relational',
                                               customer_record=CUSTOMERS['CUST-FLAGGED'])
        assert decision.allowed is False and decision.code == 'CONSENT_REVOKED'
        assert decision.consent_source == 'explicit'

    def test_enforcement_switch_skips_consent_but_not_revocation(self, monkeypatch):
        monkeypatch.setenv(ENFORCE_ENV, 'false')
        allowed = MessagingPolicy().authorize('CUST-B6', 'whatsapp', 'relational')
        assert allowed.allowed is True
        get_consent_registry().set('CUST-B6', 'whatsapp', False)
        blocked = MessagingPolicy().authorize('CUST-B6', 'whatsapp', 'relational')
        assert blocked.code == 'CONSENT_REVOKED'

    def test_email_is_not_gated(self):
        assert MessagingPolicy().authorize('CUST-B6', 'email', 'relational').code == 'NOT_GATED'

    def test_invalid_channel_rejected_by_registry(self):
        with pytest.raises(ValueError):
            get_consent_registry().set('CUST-B6', 'email', True)


class TestDailyCap:
    def test_cap_counts_across_channels_and_pending_rows(self, monkeypatch):
        monkeypatch.setenv(DAILY_CAP_ENV, '2')
        get_consent_registry().set('CUST-B6', 'whatsapp', True)
        agent = _comm()
        first = agent.send_customer_outreach(customer_id='CUST-B6', customer_name='D',
                                             email='dana@phins.ai', phone='+972501112233',
                                             template='message', channels='whatsapp')
        assert first['success'] is True
        # A pending SMS row (in-flight peer send) counts toward the cap.
        get_interaction_log().record(customer_id='CUST-B6', agent='service_desk', kind='inquiry',
                                     channel='sms', status='pending')
        third = agent.send_customer_outreach(customer_id='CUST-B6', customer_name='D',
                                             email='dana@phins.ai', phone='+972501112233',
                                             template='bill', channels='whatsapp')
        assert third['success'] is False
        assert third['code'] == 'DAILY_CAP_REACHED'
        assert third['whatsapp']['policy']['sent_today'] == 2
        # Refusals and email do not consume the cap.
        assert get_interaction_log().count_sent_today('CUST-B6') == 2

    def test_cap_is_per_utc_day(self, monkeypatch):
        monkeypatch.setenv(DAILY_CAP_ENV, '1')
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        get_interaction_log().record(customer_id='CUST-B6', agent='communication', kind='outreach',
                                     channel='whatsapp', status='sent', now=yesterday)
        assert get_interaction_log().count_sent_today('CUST-B6') == 0
        assert MessagingPolicy().authorize('CUST-B6', 'whatsapp', 'transactional').allowed is True

    def test_cap_zero_disables(self, monkeypatch):
        monkeypatch.setenv(DAILY_CAP_ENV, '0')
        for _ in range(7):
            get_interaction_log().record(customer_id='CUST-B6', agent='communication',
                                         kind='outreach', channel='sms', status='sent')
        assert MessagingPolicy().authorize('CUST-B6', 'sms', 'transactional').allowed is True

    def test_service_desk_sms_ack_respects_cap(self, monkeypatch):
        monkeypatch.setenv(DAILY_CAP_ENV, '1')
        desk = _desk()
        first = desk.handle_inquiry('CUST-B6', channel='sms', message='hi')
        assert first['acknowledgement'].success is True
        assert first['acknowledgement'].channel == 'sms'
        second = desk.handle_inquiry('CUST-B6', channel='sms', message='hi again')
        ack = second['acknowledgement']
        assert ack.success is False
        assert ack.delivery_status == 'Refused'
        assert ack.error_code == 'DAILY_CAP_REACHED'
        # The inquiry itself is still on the timeline.
        assert second['interaction']['status'] == 'refused'
        assert len(desk.interactions) == 2


# --------------------------------------------------------------------------
# OTP-verified consent capture
# --------------------------------------------------------------------------

class TestOtpConsentCapture:
    def test_otp_verified_against_whatsapp_number_records_consent(self):
        service = create_notification_service(use_mock=True)
        otp = service.send_otp(OTPRequest(
            identifier='+14155551234', channel=NotificationChannel.SMS,
            verification_type=VerificationType.ACCOUNT_ACTIVATION,
        ))
        assert otp.success
        sms_body = service._sms_provider.sent_messages[0]['message']
        code = sms_body.split(': ')[1].split('.')[0]
        agent = CustomerCommunicationAgent(notification_service=service)
        result = agent.send_welcome_package(
            customer_id='CUST-OTP', customer_name='O', email='o@phins.ai',
            whatsapp_phone='+14155551234', require_otp_validation=True,
            otp_code=code, otp_identifier='+14155551234',
        )
        assert result['success'] is True, result
        consent = get_consent_registry().explicit('CUST-OTP', 'whatsapp')
        assert consent is not None and consent.granted is True
        assert consent.source == 'otp_verified'
        # Relational WhatsApp copy is now allowed for this customer.
        follow = agent.send_customer_outreach(customer_id='CUST-OTP', customer_name='O',
                                              email='o@phins.ai', phone='+14155551234',
                                              template='message', channels='whatsapp')
        assert follow['success'] is True

    def test_failed_otp_records_nothing(self):
        service = create_notification_service(use_mock=True)
        agent = CustomerCommunicationAgent(notification_service=service)
        result = agent.send_welcome_package(
            customer_id='CUST-OTP', customer_name='O', email='o@phins.ai',
            whatsapp_phone='+14155551234', require_otp_validation=True,
            otp_code='000000', otp_identifier='+14155551234',
        )
        assert result['success'] is False
        assert get_consent_registry().get('CUST-OTP') is None
        assert get_interaction_log().for_customer('CUST-OTP') == []


# --------------------------------------------------------------------------
# Escalation
# --------------------------------------------------------------------------

class TestEscalation:
    def test_one_path_for_both_facades(self):
        audit_events = []

        class FakeAudit:
            def log(self, **kw):
                audit_events.append(kw)
                return {'id': 'AUD-1', **kw}

        from services.customer_agent.escalation import EscalationDesk
        desk = EscalationDesk(audit_service=FakeAudit())
        comm = CustomerCommunicationAgent(notification_service=create_notification_service(use_mock=True),
                                          escalation_desk=desk)
        svc = _desk(escalation_desk=desk)

        first = comm.escalate(customer_id='CUST-B6', reason='Angry about premium', actor='admin')
        report = svc.escalate_to_human('CUST-B6', 'Wants a human', assigned_team='Claims Team')

        assert first.report_id.startswith('ESC_CUST-B6_')
        assert report['report_type'] == 'Service Escalation'
        assert report['assigned_to'] == 'Claims Team'
        assert report['details']['customer_name'] == 'Dana Levi'
        assert {e.source_agent for e in desk.for_customer('CUST-B6')} == {'communication', 'service_desk'}
        assert len(audit_events) == 2
        assert all(e['action'] == 'customer_agent.escalated' for e in audit_events)
        timeline = get_interaction_log().for_customer('CUST-B6', kinds=['escalation'])
        assert len(timeline) == 2
        assert {t.metadata['report_id'] for t in timeline} == {first.report_id, report['report_id']}
        assert first.audit_id == 'AUD-1'

    def test_audit_failure_does_not_lose_the_record(self):
        class BrokenAudit:
            def log(self, **kw):
                raise RuntimeError('audit down')

        from services.customer_agent.escalation import EscalationDesk
        desk = EscalationDesk(audit_service=BrokenAudit())
        esc = desk.escalate(customer_id='CUST-B6', reason='x', source_agent='service_desk')
        assert desk.get(esc.report_id) is not None
        assert esc.audit_id is None
        assert esc.interaction_id is not None


# --------------------------------------------------------------------------
# Template registry + service desk
# --------------------------------------------------------------------------

class TestServiceDesk:
    def test_service_templates_live_in_shared_registry(self):
        ensure_service_templates()
        for template_id in SERVICE_TEMPLATES:
            assert TemplateEngine.get_template(template_id) is not None
        rendered = TemplateEngine.render_registered('service_ack', {'customer_name': 'Dana',
                                                                     'message': 'Got it.'})
        assert rendered['subject'] == 'We received your inquiry'
        assert 'Dear Dana' in rendered['body'] and 'Got it.' in rendered['body']
        assert TemplateEngine.render_registered('missing', {}) is None

    def test_register_template_validation_and_replace(self):
        with pytest.raises(ValueError):
            TemplateEngine.register_template('', body='x')
        with pytest.raises(ValueError):
            TemplateEngine.register_template('t', body='')
        TemplateEngine.register_template('b6_tmp', body='one', channel='SMS')
        assert TemplateEngine.get_template('b6_tmp')['channel'] == 'sms'
        TemplateEngine.register_template('b6_tmp', body='two')
        assert TemplateEngine.get_template('b6_tmp')['body'] == 'one'
        TemplateEngine.register_template('b6_tmp', body='two', replace=True)
        assert TemplateEngine.get_template('b6_tmp')['body'] == 'two'
        assert TemplateEngine.unregister_template('b6_tmp') is True
        assert TemplateEngine.unregister_template('b6_tmp') is False

    def test_correspondence_uses_notification_service_and_logs(self):
        desk = _desk()
        delivery = desk.send_correspondence('CUST-B6', 'premium_allocation',
                                            {'customer_name': 'Dana', 'policy_id': 'POL-1',
                                             'total_premium': '100'})
        assert isinstance(delivery, Delivery)
        assert delivery.success is True
        assert delivery.customer_id == 'CUST-B6'
        assert delivery.channel == 'email'
        assert delivery.recipient == 'd***@phins.ai'
        assert 'POL-1' in delivery.message
        row = get_interaction_log().get(delivery.interaction_id)
        assert row.kind == 'correspondence' and row.status == 'sent'
        assert row.template == 'premium_allocation'
        assert row.notification_id == delivery.notification_id

    def test_unknown_customer_and_template_raise(self):
        desk = _desk()
        with pytest.raises(ValueError):
            desk.handle_inquiry('CUST-NOBODY', 'email', 'x')
        with pytest.raises(ValueError):
            desk.send_correspondence('CUST-B6', 'no_such_template', {})

    def test_ack_falls_back_to_portal_when_no_contact(self):
        desk = _desk()
        CUSTOMERS['CUST-SILENT'] = {'id': 'CUST-SILENT', 'name': 'No Contact'}
        try:
            result = desk.handle_inquiry('CUST-SILENT', 'whatsapp', 'hello')
        finally:
            CUSTOMERS.pop('CUST-SILENT', None)
        assert result['acknowledgement'].channel == 'portal'
        assert result['acknowledgement'].success is True
        assert result['interaction']['channel'] == 'whatsapp'  # inbound channel preserved

    def test_log_interaction_and_legacy_view(self):
        desk = _desk()
        desk.log_interaction({'customer_id': 'CUST-B6', 'channel': 'phone', 'message': 'called in'})
        assert len(desk.interactions) == 1
        view = desk.interactions[0]
        assert view['channel'] == 'phone' and view['message'] == 'called in'
        assert view['handled_by'] == 'desk-1' and view['kind'] == 'note'


class TestLegacyShims:
    def test_service_agent_shim_mirrors_into_notification_manager(self):
        from service_agent import CustomerServiceAgent as Shim
        from underwriting_assistant import DivisionalReporter, NotificationManager

        nm = NotificationManager()
        reporter = DivisionalReporter()
        svc = Shim('legacy', notification_mgr=nm, reporter=reporter,
                   notification_service=create_notification_service(use_mock=True),
                   customer_lookup=CUSTOMERS.get)
        # legacy templates were imported into the shared registry
        assert TemplateEngine.get_template('uw_approved') is not None
        delivery = svc.send_correspondence('CUST-B6', 'uw_approved',
                                           {'customer_name': 'Dana', 'policy_id': 'POL-9'})
        assert delivery.success is True
        assert len(nm.delivery_queue) == 1
        assert nm.delivery_queue[0].customer_id == 'CUST-B6'
        assert nm.delivery_queue[0].metadata['interaction_id'] == delivery.interaction_id
        report = svc.escalate_to_human('CUST-B6', 'legacy path')
        assert reporter.reports[-1]['report_id'] == report['report_id']
        assert get_escalation_desk().get(report['report_id']) is not None

    def test_communication_shim_exports_same_class(self):
        import services.customer_communication_agent as shim
        from services.customer_agent import communication
        assert shim.CustomerCommunicationAgent is communication.CustomerCommunicationAgent
        assert shim.get_customer_communication_agent is communication.get_customer_communication_agent

    def test_agent_registry_points_at_new_modules(self):
        from services.agent_runtime import get_descriptor, health
        comm = get_descriptor('customer_communication')
        svc = get_descriptor('customer_service')
        assert comm.module == 'services.customer_agent.communication'
        assert svc.module == 'services.customer_agent.service_desk'
        # Health surfaces expose the shared rails (PII-free counters only).
        for agent_id in ('customer_communication', 'customer_service'):
            view = health(agent_id)
            payload = json.dumps(view, default=str)
            assert 'interaction_log' in payload and 'daily_cap' in payload


# --------------------------------------------------------------------------
# Durable in DB mode
# --------------------------------------------------------------------------

def _purge_customer_agent():
    from database.manager import DatabaseManager
    from database.models import AgentArtifact
    with DatabaseManager() as db:
        session = db.agent_artifacts.session
        session.query(AgentArtifact).filter(AgentArtifact.agent_id == 'customer_agent').delete(
            synchronize_session=False)
        session.commit()


@pytest.fixture
def db_mode(monkeypatch):
    from database import init_database
    init_database()
    monkeypatch.setattr(hs, 'db_mode_enabled', lambda: True)
    hs.reset_shared_stores()
    reset_customer_agent_state()
    _purge_customer_agent()
    yield
    hs.reset_shared_stores()
    reset_customer_agent_state()
    _purge_customer_agent()


class TestDurableState:
    def test_interactions_consent_and_escalations_survive_a_restart(self, db_mode):
        get_consent_registry().set('CUST-B6', 'whatsapp', True, actor='customer')
        _comm().send_customer_outreach(customer_id='CUST-B6', customer_name='D', email='dana@phins.ai',
                                       phone='+972501112233', template='message', channels='both')
        _desk().escalate_to_human('CUST-B6', 'durable?')

        from database.manager import DatabaseManager
        with DatabaseManager() as db:
            assert db.agent_artifacts.count_for('customer_agent', 'interaction') == 3  # email, wa, escalation
            assert db.agent_artifacts.count_for('customer_agent', 'consent') == 1
            assert db.agent_artifacts.count_for('customer_agent', 'escalation') == 1

        # Fresh process: caches gone, rows come back from the table.
        hs.reset_shared_stores()
        reset_customer_agent_state()
        timeline = customer_timeline('CUST-B6')
        assert len(timeline['interactions']) == 3
        assert timeline['consent']['channels']['whatsapp']['granted'] is True
        assert len(timeline['escalations']) == 1
        assert timeline['sent_today'] == 1  # the WhatsApp leg
        # The cap on a peer instance counts the durable rows.
        assert get_interaction_log().count_sent_today('CUST-B6') == 1


# --------------------------------------------------------------------------
# HTTP wiring
# --------------------------------------------------------------------------

def _http(method, url, data=None, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    body = json.dumps(data).encode('utf-8') if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw)
        except Exception:
            return exc.code, {'error': raw}


class TestHttpWiring:
    def test_consent_and_interactions_routes(self):
        import web_portal.server as portal

        base = os.environ.get('TEST_BASE_URL', 'http://127.0.0.1:8000')
        status, login = _http('POST', f'{base}/api/login', {'username': 'admin', 'password': 'admin123'})
        if status != 200 or not login.get('token'):
            pytest.skip('admin login unavailable in this environment')
        token = login['token']

        portal.CUSTOMERS['CUST-B6-HTTP'] = {
            'id': 'CUST-B6-HTTP', 'name': 'HTTP Consent', 'email': 'b6@phins.ai', 'phone': '+15555550177',
        }

        # Unauthenticated callers are refused.
        assert _http('GET', f'{base}/api/admin/customers/CUST-B6-HTTP/interactions')[0] in (401, 403)
        assert _http('POST', f'{base}/api/admin/customers/CUST-B6-HTTP/consent', {'channel': 'whatsapp'})[0] in (401, 403)

        # Relational WhatsApp is refused before consent…
        status, payload = _http('POST', f'{base}/api/admin/customers/CUST-B6-HTTP/contact',
                                {'template': 'message', 'channels': 'whatsapp'}, token=token)
        assert status == 400, payload
        assert payload['code'] == 'CONSENT_REQUIRED'

        # …granted through the consent route…
        status, payload = _http('POST', f'{base}/api/admin/customers/CUST-B6-HTTP/consent',
                                {'channel': 'whatsapp', 'granted': True, 'note': 'phone call'}, token=token)
        assert status == 200, payload
        assert payload['consent']['channels']['whatsapp']['granted'] is True
        assert payload['consent']['channels']['whatsapp']['actor'] == 'admin'

        # …then allowed.
        status, payload = _http('POST', f'{base}/api/admin/customers/CUST-B6-HTTP/contact',
                                {'template': 'message', 'channels': 'whatsapp'}, token=token)
        assert status == 200, payload
        assert payload['whatsapp']['success'] is True

        # Timeline shows refusal, consent change, and the send; recipients are masked.
        status, view = _http('GET', f'{base}/api/admin/customers/CUST-B6-HTTP/interactions', token=token)
        assert status == 200, view
        kinds = [(i['kind'], i['status']) for i in view['interactions']]
        assert ('outreach', 'refused') in kinds
        assert ('consent', 'logged') in kinds
        assert ('outreach', 'sent') in kinds
        assert view['consent']['channels']['whatsapp']['granted'] is True
        assert view['sent_today'] == 1
        assert view['policy']['daily_cap'] >= 0
        assert '+15555550177' not in json.dumps(view)

        # Revoke, and transactional copy is blocked too.
        _http('POST', f'{base}/api/admin/customers/CUST-B6-HTTP/consent',
              {'channel': 'whatsapp', 'granted': False}, token=token)
        status, payload = _http('POST', f'{base}/api/admin/customers/CUST-B6-HTTP/contact',
                                {'template': 'bill', 'channels': 'whatsapp'}, token=token)
        assert status == 400 and payload['code'] == 'CONSENT_REVOKED'

        # Bad channel and unknown customer.
        status, payload = _http('POST', f'{base}/api/admin/customers/CUST-B6-HTTP/consent',
                                {'channel': 'email'}, token=token)
        assert status == 400 and 'error' in payload
        status, payload = _http('GET', f'{base}/api/admin/customers/CUST-NOPE/interactions', token=token)
        assert status == 404 and payload['error'] == 'Customer not found'
