"""Mislaka (מסלקה) schema mappings — field names, interface / product / status
codes from the official XSD schemas — plus the lookup tables the parsers use.

Moved verbatim from ``services/pension_data_agent.py`` (B5). The tag-variant
tables at the bottom are precompiled once at import so the XML parser never
recomputes hyphen-stripped or CamelCase spellings per element.
"""

import re
from typing import Any, Dict, Optional, Tuple


class MislakaSchemaMapping:
    """
    Field mappings from Mislaka XSD schemas based on ChatGPT analysis.
    Based on:
    - mivneachid_holdings_*.xsd (v9.7.7)
    - mivneachid_mimshak_pitzuim_*.XSD (v5.9.38)
    - Holdings Interface V9.7.7 Excel specs
    - Severance Interface V5.9.38 Excel specs
    """
    
    # Interface type codes (SUG-MIMSHAK)
    INTERFACE_CODES = {
        # Holdings interfaces
        1: {'name': 'Holdings', 'he': 'אחזקות', 'schema': 'holdings_v9'},
        2: {'name': 'PreAdvice', 'he': 'הודעה מקדימה', 'schema': 'holdings_v9'},
        3: {'name': 'HoldingsPreAdvice', 'he': 'אחזקות + הודעה מקדימה', 'schema': 'holdings_v9'},
        
        # Severance interfaces (pitzuim)
        17: {'name': 'Severance', 'he': 'פיצויים', 'schema': 'pitzuim_v5'},
        9300: {'name': 'SeveranceRequest', 'he': 'בקשה לנתוני פיצויים', 'schema': 'pitzuim_9300'},
        9301: {'name': 'SeveranceResponse', 'he': 'תשובה לבקשת פיצויים', 'schema': 'pitzuim_9301'},
        9302: {'name': 'SeveranceQuery', 'he': 'שאילתת פיצויים', 'schema': 'pitzuim_9302'},
        9303: {'name': 'SeveranceData', 'he': 'נתוני פיצויים', 'schema': 'pitzuim_9303'},
        9305: {'name': 'SeveranceUpdate', 'he': 'עדכון פיצויים', 'schema': 'pitzuim_9305'},
        9306: {'name': 'SeveranceConfirm', 'he': 'אישור פיצויים', 'schema': 'pitzuim_9306'},
        
        # Event interface
        6: {'name': 'Events', 'he': 'אירועים', 'schema': 'events_v7'},
        21: {'name': 'Events', 'he': 'אירועים', 'schema': 'events_v7'},
        
        # Transference interface
        22: {'name': 'Transference', 'he': 'העברה', 'schema': 'transference_v3'},
        33: {'name': 'Transference', 'he': 'העברה', 'schema': 'transference_v3'},
    }
    
    # Product type codes (SUG-MUTZAR / KOD-SUG-MUTZAR)
    PRODUCT_TYPE_CODES = {
        # Pension funds - קרנות פנסיה
        '1': {'name': 'pension_fund_new', 'he': 'קרן פנסיה חדשה', 'en': 'New Pension Fund'},
        '2': {'name': 'pension_fund_old', 'he': 'קרן פנסיה ותיקה', 'en': 'Old Pension Fund'},
        '3': {'name': 'pension_fund_comprehensive', 'he': 'קרן פנסיה מקיפה', 'en': 'Comprehensive Pension'},
        
        # Provident funds (Gemel) - קופות גמל
        '4': {'name': 'provident_fund', 'he': 'קופת גמל', 'en': 'Provident Fund'},
        '5': {'name': 'central_severance_fund', 'he': 'קופה מרכזית לפיצויים', 'en': 'Central Severance Fund'},
        '6': {'name': 'education_fund', 'he': 'קרן השתלמות', 'en': 'Education Fund'},
        
        # Insurance - ביטוח
        '7': {'name': 'managers_insurance', 'he': 'ביטוח מנהלים', 'en': 'Managers Insurance'},
        '8': {'name': 'life_insurance', 'he': 'ביטוח חיים', 'en': 'Life Insurance'},
        '9': {'name': 'pension_insurance', 'he': 'ביטוח פנסיוני', 'en': 'Pension Insurance'},
        
        # Others
        '10': {'name': 'savings_policy', 'he': 'פוליסת חיסכון', 'en': 'Savings Policy'},
        '11': {'name': 'risk_insurance', 'he': 'ביטוח ריסק', 'en': 'Risk Insurance'},
        '12': {'name': 'disability_insurance', 'he': 'ביטוח אובדן כושר עבודה', 'en': 'Disability Insurance'},
    }
    
    # Status codes (STATUS-POLISA-O-CHESHBON)
    STATUS_CODES = {
        '1': {'name': 'active', 'he': 'פעיל', 'en': 'Active'},
        '2': {'name': 'frozen', 'he': 'מוקפא', 'en': 'Frozen'},
        '3': {'name': 'closed', 'he': 'סגור', 'en': 'Closed'},
        '4': {'name': 'paid_up', 'he': 'משולם', 'en': 'Paid Up'},
        '5': {'name': 'transferred', 'he': 'הועבר', 'en': 'Transferred'},
        '6': {'name': 'pending', 'he': 'בהמתנה', 'en': 'Pending'},
    }
    
    # Environment codes (KOD-SVIVAT-AVODA)
    ENVIRONMENT_CODES = {
        '1': 'Test',
        '2': 'Production',
    }
    
    # Sender/Recipient type codes (KOD-SHOLECH / KOD-NIMAAN)
    ENTITY_TYPE_CODES = {
        '1': {'he': 'יצרן', 'en': 'Provider/Institution'},
        '2': {'he': 'מסלקה', 'en': 'Clearinghouse'},
        '3': {'he': 'מפיץ/סוכן', 'en': 'Distributor/Agent'},
        '4': {'he': 'עמית/חוסך', 'en': 'Saver/Client'},
        '5': {'he': 'מעסיק', 'en': 'Employer'},
        '6': {'he': 'לשכת שירות', 'en': 'Service Bureau'},
    }
    
    # ID type codes (SUG-MEZAHE-SHOLECH / SUG-ZIHUI-LAKOACH)
    ID_TYPE_CODES = {
        '1': {'he': 'ח.פ (חברה)', 'en': 'Company ID'},
        '2': {'he': 'ח.צ (שותפות)', 'en': 'Partnership ID'},
        '3': {'he': 'תעודת זהות', 'en': 'ID Card'},
        '4': {'he': 'דרכון', 'en': 'Passport'},
        '5': {'he': 'רישיון עסק', 'en': 'Business License'},
        '7': {'he': 'עמותה', 'en': 'Non-profit'},
        '8': {'he': 'אגודה שיתופית', 'en': 'Cooperative'},
        '9': {'he': 'חברה ממשלתית', 'en': 'Government Company'},
    }
    
    # Header field mappings (KoteretKovetz)
    HEADER_FIELDS = {
        'SUG-MIMSHAK': 'interface_code',
        'SugMimshak': 'interface_code',
        'MISPAR-GIRSAT-XML': 'schema_version',
        'MisparGirsatXml': 'schema_version',
        'TAARICH-BITZUA': 'created_at',
        'TaarichBitzua': 'created_at',
        'TAARICH-HAFAKAT-HADOCH': 'report_date',
        'TaarichHafakatHadoch': 'report_date',
        'MISPAR-HAKOVETZ': 'file_id',
        'MisparHakovetz': 'file_id',
        'KOD-SVIVAT-AVODA': 'environment',
        'KodSvivatAvoda': 'environment',
        'KOD-SHOLEACH': 'sender_type',
        'KodSholeach': 'sender_type',
        'SUG-MEZAHE-SHOLECH': 'sender_id_type',
        'SugMezaheSholech': 'sender_id_type',
        'MISPAR-ZIHUI-SHOLECH': 'sender_id',
        'MisparZihuiSholech': 'sender_id',
        'SHEM-SHOLEACH': 'sender_name',
        'ShemSholeach': 'sender_name',
        'KOD-NIMAAN': 'recipient_type',
        'KodNimaan': 'recipient_type',
        'SHEM-MEKABEL': 'receiver_name',
        'ShemMekabel': 'receiver_name',
    }
    
    # Client field mappings (YeshutLakoach)
    CLIENT_FIELDS = {
        'MISPAR-ZIHUI-LAKOACH': 'id_number',
        'MisparZihuiLakoach': 'id_number',
        'MISPARZEHUT': 'id_number',
        'MisparZehut': 'id_number',
        'MISPAR-ZEHUT': 'id_number',
        'MisparZehutLakoach': 'id_number',
        'MISPAR-ZIHUY': 'id_number',
        'MisparZihuy': 'id_number',
        'MISPAR-ZIHUY-MITPATZEACH': 'id_number',
        'MisparZihuiMitpatcheach': 'id_number',
        'ZEHUT': 'id_number',
        'TEUDAT-ZEHUT': 'id_number',
        'TeudatZehut': 'id_number',
        'SUG-ZIHUI-LAKOACH': 'id_type',
        'SugZihuiLakoach': 'id_type',
        'SugZihuiMitpatcheach': 'id_type',
        'SHEM-PRATI': 'first_name',
        'ShemPrati': 'first_name',
        'SHEM-MISHPACHA': 'last_name',
        'ShemMishpacha': 'last_name',
        'SHEM-LAKOACH': 'full_name',
        'ShemLakoach': 'full_name',
        'TAARICH-LEYDA': 'birth_date',
        'TaarichLeyda': 'birth_date',
        'MIN': 'gender',
        'KTOVET': 'address',
        'Ktovet': 'address',
        'YISHUV': 'city',
        'Yishuv': 'city',
        'TELEFON': 'phone',
        'Telefon': 'phone',
        'EMAIL': 'email',
        'Email': 'email',
    }
    
    # Provider field mappings (YeshutYatzran)
    PROVIDER_FIELDS = {
        'KOD-YATZRAN': 'code',
        'KodYatzran': 'code',
        'KOD-MEZAHE-YATZRAN': 'code',
        'KodMezaheYatzran': 'code',
        'SHEM-YATZRAN': 'name',
        'ShemYatzran': 'name',
        'SUG-YATZRAN': 'provider_type',
        'SugYatzran': 'provider_type',
    }
    
    # Product field mappings (Mutzar)
    PRODUCT_FIELDS = {
        'KOD-MUTZAR': 'code',
        'KodMutzar': 'code',
        'SHEM-MUTZAR': 'name',
        'ShemMutzar': 'name',
        'SUG-MUTZAR': 'product_type',
        'SugMutzar': 'product_type',
        'KOD-SUG-MUTZAR': 'product_type_code',
        'KodSugMutzar': 'product_type_code',
        'SUG-KUPA': 'sub_type',
        'SugKupa': 'sub_type',
        'STATUS-MUTZAR': 'status',
        'StatusMutzar': 'status',
        'TAARICH-TCHILAT-MUTZAR': 'start_date',
        'TaarichTchilatMutzar': 'start_date',
    }
    
    # Account field mappings (HeshbonOPolisa / PirteiHeshbon)
    ACCOUNT_FIELDS = {
        # Policy number
        'MISPAR-POLISA-O-HESHBON': 'policy_number',
        'MisparPolisaOHeshbon': 'policy_number',
        'MISPAR-POLISA': 'policy_number',
        'MisparPolisa': 'policy_number',
        'MISPAR-HESHBON': 'policy_number',
        'MisparHeshbon': 'policy_number',
        'MISPAR-CHESHBON': 'policy_number',
        'MisparCheshbon': 'policy_number',
        
        # Status
        'STATUS-POLISA-O-CHESHBON': 'status_code',
        'StatusPolisaOCheshbon': 'status_code',
        'STATUS-HESHBON': 'status_code',
        'StatusHeshbon': 'status_code',
        
        # Start date
        'TAARICH-TCHILAT-HESHBON': 'start_date',
        'TaarichTchilatHeshbon': 'start_date',
        'TAARICH-TCHILAT-BITUACH': 'start_date',
        'TaarichTchilatBituach': 'start_date',
        
        # Balances — official Mivne Achid / Swiftness holdings aliases
        'SALDO': 'total_balance',
        'Saldo': 'total_balance',
        'YITRA-KOLELET': 'total_balance',
        'YitraKolelet': 'total_balance',
        'SCHUM-HATZBARA': 'total_balance',
        'SchumHatzbara': 'total_balance',
        'SCHUM-TZVIRA': 'total_balance',
        'SchumTzvira': 'total_balance',
        'SCHUM-TZVIRA-NOCHECHIT': 'total_balance',
        'SchumTzviraNochechit': 'total_balance',
        'TOTAL-CHISACHON': 'total_balance',
        'TotalChisachon': 'total_balance',
        'TOTAL-CHISACHON-MTZBR': 'total_balance',
        'TotalChisachonMtzbr': 'total_balance',
        'TZVIRAT-KSAFIM': 'total_balance',
        'TzviratKsafim': 'total_balance',
        'ERECH-PIDYON': 'total_balance',
        'ErechPidyon': 'total_balance',
        'ERECH-PIDYON-NOCHECHI': 'total_balance',
        'ErechPidyonNochechi': 'total_balance',
        'SACH-YITRA': 'total_balance',
        'SachYitra': 'total_balance',
        'SACH-YITRA-NOCHECHIT': 'total_balance',
        'YITRA-TZVURA': 'total_balance',
        'YitraTzvura': 'total_balance',
        'TOTAL-SAVING': 'total_balance',
        'TotalSaving': 'total_balance',
        'YITRA-CHISACHON': 'savings_balance',
        'YitraChisachon': 'savings_balance',
        'YITRAT-TAGMULIM': 'savings_balance',
        'YitratTagmulim': 'savings_balance',
        'TOTAL-CHISACHON-TAGMULIM': 'savings_balance',
        'TotalChisachonTagmulim': 'savings_balance',
        'YITRA-PITZUIM': 'severance_balance',
        'YitraPitzuim': 'severance_balance',
        'YITRAT-PITZUIM': 'severance_balance',
        'YitratPitzuim': 'severance_balance',
        'TOTAL-CHISACHON-PITZUIM': 'severance_balance',
        'TotalChisachonPitzuim': 'severance_balance',
        'KFIFA-PITZUIM': 'severance_balance',
        'KfifaPitzuim': 'severance_balance',
        'PITZUEY-MAASIK': 'employer_severance',
        'PitzueyMaasik': 'employer_severance',
        'YITRA-TAGMULIM': 'compensation_balance',
        'YitraTagmulim': 'compensation_balance',
        
        # Investment track
        'MASLUL-HASHKAA': 'investment_track',
        'MaslulHashkaa': 'investment_track',
        'KOD-MASLUL': 'investment_track_code',
        'KodMaslul': 'investment_track_code',
        
        # Management fees
        'DMEY-NIHUL-CHISACHON': 'management_fee_savings',
        'DmeyNihulChisachon': 'management_fee_savings',
        'DMEY-NIHUL-HAFKADOT': 'management_fee_deposits',
        'DmeyNihulHafkadot': 'management_fee_deposits',
        
        # Employer
        'KOD-MAASIK': 'employer_id',
        'KodMaasik': 'employer_id',
        'SHEM-MAASIK': 'employer_name',
        'ShemMaasik': 'employer_name',
        'MPR-MAASIK-BE-YATZRAN': 'employer_internal_id',
        'MprMaasikBeYatzran': 'employer_internal_id',
        
        # Coverage (for insurance)
        'SACH-KISUY': 'coverage_amount',
        'SachKisuy': 'coverage_amount',
        'KITZBA-CHODSHIT': 'monthly_pension',
        'KitzbaChodshit': 'monthly_pension',
        'KISUY-MAVET': 'death_coverage',
        'KisuyMavet': 'death_coverage',
        # SchumeiBituahYesodi: the lump-sum death benefit. The agent column is
        # "סכום ביטוח למקרה מוות – חד פעמי". It is a face amount, not צבירה.
        'SCHUM-BITUH-LEMAVET': 'death_lump_sum',
        'SCHUM-BITUACH-LEMAVET': 'death_lump_sum',
        'SCHUM-BITUH-LEMIKRE-MAVET': 'death_lump_sum',
        'KISUY-NECHUT': 'disability_coverage',
        'KisuyNechut': 'disability_coverage',
        'DMEY-BITUACH-MAVET': 'death_premium',
        'DmeyBituachMavet': 'death_premium',
        'PREMIA-MAVET': 'death_premium',
        'PremiaMavet': 'death_premium',
        'DMEY-BITUACH-NECHUT': 'disability_premium',
        'DmeyBituachNechut': 'disability_premium',
        'PREMIA-NECHUT': 'disability_premium',
        'PremiaNechut': 'disability_premium',
        'KISUY-OVDAN-KOSHER': 'work_disability_coverage',
        'KisuyOvdanKosher': 'work_disability_coverage',
        'KISUY-AKW': 'work_disability_coverage',
        'KisuyAkw': 'work_disability_coverage',
        'DMEY-BITUACH-AKW': 'work_disability_premium',
        'DmeyBituachAkw': 'work_disability_premium',
        'KISUY-NECHUT-KAVA': 'invalidity_coverage',
        'KisuyNechutKava': 'invalidity_coverage',
        'DMEY-BITUACH-NECHUT-KAVA': 'invalidity_premium',
        'KISUY-SHICHRUR': 'waiver_coverage',
        'KisuyShichrur': 'waiver_coverage',
        'DMEY-BITUACH-SHICHRUR': 'waiver_premium',
        'DmeyBituachShichrur': 'waiver_premium',
        'KISUY-SHEERIM': 'survivors_coverage',
        'KisuySheerim': 'survivors_coverage',
        'DMEY-BITUACH-SHEERIM': 'survivors_premium',
        'DmeyBituachSheerim': 'survivors_premium',
        'KISUY-SIUDI': 'ltc_coverage',
        'KisuySiudi': 'ltc_coverage',
        'KISUY-SIUD': 'ltc_coverage',
        'DMEY-BITUACH-SIUD': 'ltc_premium',
        'DmeyBituachSiud': 'ltc_premium',
        
        # Section 14
        'SEIF-14': 'section14',
        'Seif14': 'section14',
        'ARTICLE14': 'section14',
        'article14': 'section14',
        'SI14': 'section14',
        'SACHIF-14': 'section14',
        'TAARICH-SEIF-14': 'section14_date',
        'TaarichSeif14': 'section14_date',
    }
    
    # Contribution field mappings (NetuneiHafrasha / PirteiHafrasha)
    CONTRIBUTION_FIELDS = {
        'CHODESH-DIO': 'period',
        'ChodeshDio': 'period',
        'CHODESH': 'period',
        'Chodesh': 'period',
        'TKUFA': 'period',
        'Tkufa': 'period',
        
        'MISPAR-ZIHUI-LAKOACH': 'employee_id',
        'KOD-MAASIK': 'employer_id',
        'SHEM-MAASIK': 'employer_name',
        
        'HAFRASHA-OVED': 'employee_amount',
        'HafrashaOved': 'employee_amount',
        'HAFRASHA-MAASIK': 'employer_amount',
        'HafrashaMaasik': 'employer_amount',
        'HAFRASHA-PITZUIM': 'severance_amount',
        'HafrashaPitzuim': 'severance_amount',
        'SACH-HAFRASHA': 'total_amount',
        'SachHafrasha': 'total_amount',
        
        'SACHAR-KOVEA': 'salary_base',
        'SacharKovea': 'salary_base',
        
        'STATUS-HAFRASHA': 'status',
        'StatusHafrasha': 'status',
        'TAARICH-KLITA': 'received_date',
        'TaarichKlita': 'received_date',
    }
    
    # Severance field mappings (NetuneiPitzuim)
    SEVERANCE_FIELDS = {
        'MISPAR-ZIHUI-LAKOACH': 'employee_id',
        'MISPAR-POLISA': 'policy_number',
        'KOD-MAASIK': 'employer_id',
        'SHEM-MAASIK': 'employer_name',
        
        'KSF-PITZUIM-TZVUR': 'total_severance',
        'KsfPitzuimTzvur': 'total_severance',
        'SACH-PITZUIM': 'total_severance',
        'SachPitzuim': 'total_severance',
        'YITRAT-PITZUIM': 'total_severance',
        'YitratPitzuim': 'total_severance',
        'TOTAL-PITZUIM': 'total_severance',
        'ERECH-PIDYON-PITZUIM': 'total_severance',
        'ERECH-PIDYON-PITZUIM-MAASEK-NOCHECHI': 'total_severance',
        'PITZUIM-LMSHICHA': 'available_severance',
        'PitzuimLmshicha': 'available_severance',
        'PITZUIM-SEIF14': 'section14_amount',
        'PitzuimSeif14': 'section14_amount',
        
        'SEIF-14': 'section14',
        'article14': 'section14',
        'ARTICLE14': 'section14',
        'ACHUZ-SEIF-14': 'section14_percentage',
        'AchuzSeif14': 'section14_percentage',
        
        'TAARICH-TCHILAT-AVODA': 'employment_start',
        'TaarichTchilatAvoda': 'employment_start',
        'TAARICH-SIUM-AVODA': 'employment_end',
        'TaarichSiumAvoda': 'employment_end',
    }
    
    # Known insurance company codes
    INSURANCE_COMPANIES = {
        '1': 'מגדל',
        '2': 'הראל',
        '3': 'כלל',
        '4': 'פניקס',
        '5': 'הפניקס',
        '6': 'מנורה מבטחים',
        '7': 'איילון',
        '8': 'ביטוח ישיר',
        '9': 'שירביט',
        '10': 'הכשרה',
        '11': 'ליברה',
        '12': 'אקסא',
    }
    
    # Known pension fund codes
    PENSION_FUNDS = {
        '512': 'מיטב דש',
        '513': 'אלטשולר שחם',
        '514': 'מור',
        '515': 'הלמן אלדובי',
        '516': 'אנליסט',
        '517': 'פסגות',
        '518': 'מנורה מבטחים פנסיה',
        '519': 'הראל פנסיה',
        '520': 'מגדל מקפת',
        '521': 'כלל פנסיה',
    }


# ---------------------------------------------------------------------------
# Precompiled lookups (B5)
# ---------------------------------------------------------------------------

def tag_variants(tag: str) -> Tuple[str, ...]:
    """The spellings ``_find_text`` tries for a schema tag, in order: exact,
    hyphens removed, CamelCase. Duplicates are dropped but order is kept."""
    variants = [tag, tag.replace('-', ''), ''.join(w.capitalize() for w in tag.split('-'))]
    seen = []
    for v in variants:
        if v not in seen:
            seen.append(v)
    return tuple(seen)


def _compile(mapping: Dict[str, str]) -> Tuple[Tuple[str, str, Tuple[str, ...]], ...]:
    return tuple((xml_tag, field_name, tag_variants(xml_tag)) for xml_tag, field_name in mapping.items())


class CompiledFields:
    """``(xml_tag, field_name, variants)`` triples per schema section, built once."""

    HEADER = _compile(MislakaSchemaMapping.HEADER_FIELDS)
    CLIENT = _compile(MislakaSchemaMapping.CLIENT_FIELDS)
    PROVIDER = _compile(MislakaSchemaMapping.PROVIDER_FIELDS)
    PRODUCT = _compile(MislakaSchemaMapping.PRODUCT_FIELDS)
    ACCOUNT = _compile(MislakaSchemaMapping.ACCOUNT_FIELDS)
    CONTRIBUTION = _compile(MislakaSchemaMapping.CONTRIBUTION_FIELDS)
    SEVERANCE = _compile(MislakaSchemaMapping.SEVERANCE_FIELDS)

    ACCOUNT_NUMERIC = frozenset({
        'total_balance', 'savings_balance', 'severance_balance',
        'employer_severance', 'compensation_balance', 'coverage_amount',
        'monthly_pension', 'management_fee_savings', 'management_fee_deposits',
        'death_coverage', 'death_lump_sum', 'disability_coverage', 'death_premium', 'disability_premium',
        'work_disability_coverage', 'work_disability_premium',
        'invalidity_coverage', 'invalidity_premium',
        'waiver_coverage', 'waiver_premium',
        'survivors_coverage', 'survivors_premium',
        'ltc_coverage', 'ltc_premium',
    })
    CONTRIBUTION_NUMERIC = frozenset({
        'employee_amount', 'employer_amount', 'severance_amount', 'total_amount', 'salary_base',
    })
    SEVERANCE_NUMERIC = frozenset({
        'total_severance', 'available_severance', 'section14_amount', 'section14_percentage',
    })
    TRUTHY = frozenset({'1', 'כן', 'true', 'True', 'Y', 'yes'})


# ---------------------------------------------------------------------------
# Hebrew / Swiftness tabular headers (Excel, CSV, ZIP affiliated reports)
# ---------------------------------------------------------------------------

# Official Swiftness "דוח מידע מרוכז" and Mislaka Excel/CSV column labels.
# Keys are stored after ``normalize_hebrew_header`` so gershayim / punctuation
# variants collapse onto one lookup.
HEBREW_COLUMN_FIELDS: Dict[str, str] = {
    'שם': 'full_name',
    'שם מלא': 'full_name',
    'שם החוסך': 'full_name',
    'שם הלקוח': 'full_name',
    'שם המבוטח': 'full_name',
    'שם פרטי': 'first_name',
    'שם משפחה': 'last_name',
    'תעודת זהות': 'id_number',
    'ת.ז': 'id_number',
    'ת"ז': 'id_number',
    'מספר זהות': 'id_number',
    'מספר ת.ז': 'id_number',
    'מספר תעודת זהות': 'id_number',
    'מזהה לקוח': 'id_number',
    'id_number': 'id_number',
    'customer_id': 'id_number',
    'national_id': 'id_number',
    'תאריך לידה': 'birth_date',
    'טלפון': 'phone',
    'נייד': 'mobile',
    'דוא"ל': 'email',
    'אימייל': 'email',
    'כתובת': 'address',
    'יצרן': 'provider',
    'שם יצרן': 'provider',
    'חברה': 'provider',
    'שם חברה': 'provider',
    'גוף מוסדי': 'provider',
    'שם הגוף המוסדי': 'provider',
    'מוצר': 'product_name',
    'שם מוצר': 'product_name',
    'שם המוצר': 'product_name',
    'סוג מוצר': 'product_type',
    'סוג קופה': 'product_type',
    'סוג תוכנית': 'product_type',
    'מספר פוליסה': 'policy_number',
    'מס פוליסה': 'policy_number',
    "מס' פוליסה": 'policy_number',
    'מספר חשבון': 'policy_number',
    'מס חשבון': 'policy_number',
    'מספר פוליסה/חשבון': 'policy_number',
    # Bare יתרה is the ledger balance column. It is not סה״כ צבירה and must
    # not be added to סה"כ חיסכון. Official accumulation headers stay on
    # total_balance (XML TOTAL-CHISACHON and ``סה״כ צבירה``).
    'יתרה': 'balance',
    'יתרה כוללת': 'total_balance',
    'סך צבירה': 'total_balance',
    'צבירה': 'total_balance',
    'סה"כ צבירה': 'total_balance',
    'סך הכל צבירה': 'total_balance',
    'סכום צבירה': 'total_balance',
    'צבירה כוללת': 'total_balance',
    'ערך פדיון': 'total_balance',
    'ערך פדיון נוכחי': 'total_balance',
    'סה"כ חיסכון': 'savings_balance',
    'סך חיסכון': 'savings_balance',
    'סך הכל חיסכון': 'savings_balance',
    'חיסכון': 'savings_balance',
    'יתרת תגמולים': 'tagmulim_balance',
    'תגמולים': 'tagmulim_balance',
    'יתרת פיצויים': 'severance_balance',
    'פיצויים': 'severance_balance',
    'סכום פיצויים': 'severance_balance',
    'סה"כ פיצויים': 'severance_balance',
    'פיצויי פיטורין': 'severance_balance',
    'יתרת פיצויים מעסיק': 'severance_balance',
    'דמי ניהול': 'management_fee',
    'דמי ניהול מצבירה': 'management_fee_savings',
    'ד"נ מצבירה': 'management_fee_savings',
    'דמי ניהול מהפקדות': 'management_fee_deposits',
    'דמי ניהול מהפקדה': 'management_fee_deposits',
    'ד"נ מהפקדות': 'management_fee_deposits',
    'ד"נ מהפקדה': 'management_fee_deposits',
    'עמלה': 'management_fee',
    'סטטוס': 'status',
    'מצב': 'status',
    'סטטוס פוליסה': 'status',
    'מצב חשבון': 'status',
    'סעיף 14': 'section14',
    'סעיף14': 'section14',
    'מעסיק': 'employer_name',
    'שם מעסיק': 'employer_name',
    'ביטוח חיים': 'death_coverage',
    'כיסוי מוות': 'death_coverage',
    # Exact column from insurer / Swiftness grids. Longer than ביטוח חיים so
    # the substring pass cannot fold it into the generic life cover.
    'סכום ביטוח למקרה מוות - חד פעמי': 'death_lump_sum',
    'פרמיה ביטוח חיים': 'death_premium',
    'פרמיית ביטוח חיים': 'death_premium',
    'עלות ביטוח חיים': 'death_premium',
    'פרמיית חיים': 'death_premium',
    'פרמיה חיים': 'death_premium',
    'אובדן כושר': 'disability_coverage',
    'אבדן כושר עבודה': 'disability_coverage',
    'אובדן כושר עבודה': 'disability_coverage',
    'כיסוי אכ"ע': 'disability_coverage',
    'פרמיה אבדן כושר עבודה': 'disability_premium',
    'פרמיה אובדן כושר עבודה': 'disability_premium',
    'פרמיה אבדן כושר': 'disability_premium',
    'פרמיה אובדן כושר': 'disability_premium',
    'עלות אכ"ע': 'disability_premium',
    'עלות אובדן כושר': 'disability_premium',
    'פרמיית אכ"ע': 'disability_premium',
    'כיסוי נכות': 'invalidity_coverage',
    'נכות': 'invalidity_coverage',
    'פרמיה נכות': 'invalidity_premium',
    'עלות נכות': 'invalidity_premium',
    'שחרור': 'waiver_coverage',
    'שחרור מפרמיה': 'waiver_coverage',
    'פרמיה שחרור': 'waiver_premium',
    'עלות שחרור': 'waiver_premium',
    'שארים': 'survivors_coverage',
    'כיסוי שארים': 'survivors_coverage',
    'פרמיה שארים': 'survivors_premium',
    'עלות שארים': 'survivors_premium',
    'סיעוד': 'ltc_coverage',
    'ביטוח סיעודי': 'ltc_coverage',
    'פרמיה סיעוד': 'ltc_premium',
    'עלות סיעוד': 'ltc_premium',
    'סה"כ פרמיה חודשית': 'monthly_premium',
    'סך פרמיה חודשית': 'monthly_premium',
    'פרמיה חודשית': 'monthly_premium',
    'תאריך תחילה': 'start_date',
    'תחילת ביטוח': 'start_date',
    'תאריך הצטרפות': 'start_date',
    'תאריך נזילות': 'liquidity_date',
    'הפקדה אחרונה': 'last_deposit',
    'תאריך הפקדה אחרונה': 'last_deposit_date',
    'סוג הפרשה': 'contribution_type',
    'תאריך סטטוס': 'status_date',
    'מסלול השקעה': 'investment_track',
    'אחוז במסלול': 'track_percent',
    'תשואה': 'yield_rate',
}

_HEBREW_PUNCT_TRANSLATION = str.maketrans({
    '\u05f4': '"',   # ״ gereshayim
    '\u201c': '"',
    '\u201d': '"',
    '\u05f3': "'",   # ׳ geresh
    '\u2018': "'",
    '\u2019': "'",
})

_HEADER_SPACE_RE = re.compile(r'\s+')
_HEADER_DASH_RE = re.compile(r'\s*-\s*')
# Hyphen, en dash, em dash, minus — the death-benefit column uses "–".
_DASH_TRANSLATION = str.maketrans({
    '\u2010': '-',
    '\u2011': '-',
    '\u2012': '-',
    '\u2013': '-',
    '\u2014': '-',
    '\u2212': '-',
})

# Consultant label for SCHUM-BITUH-LEMAVET when payment is a single sum.
DEATH_LUMP_SUM_LABEL = 'סכום ביטוח למקרה מוות – חד פעמי'


def normalize_hebrew_header(name: str) -> str:
    """Collapse Swiftness/Mislaka header punctuation so ``סה״כ צבירה`` matches ``סה"כ צבירה``."""
    text = str(name or '').strip().translate(_HEBREW_PUNCT_TRANSLATION).translate(_DASH_TRANSLATION)
    text = _HEADER_DASH_RE.sub(' - ', text)
    text = _HEADER_SPACE_RE.sub(' ', text)
    if text.endswith('.'):
        text = text[:-1].rstrip()
    if text in {'ת.ז.', 'ת"ז.'}:
        text = text[:-1]
    return text


def map_hebrew_column(column_name: str) -> Optional[str]:
    """Map a Hebrew/English tabular header onto the pension field name."""
    raw = str(column_name or '').strip()
    if not raw:
        return None
    normalized = normalize_hebrew_header(raw)
    if normalized in HEBREW_COLUMN_FIELDS:
        return HEBREW_COLUMN_FIELDS[normalized]
    if raw in HEBREW_COLUMN_FIELDS:
        return HEBREW_COLUMN_FIELDS[raw]

    matches = []
    for hebrew_name, field_name in HEBREW_COLUMN_FIELDS.items():
        if hebrew_name in normalized or hebrew_name in raw:
            matches.append((len(hebrew_name), field_name))
    if matches:
        matches.sort(key=lambda item: item[0], reverse=True)
        return matches[0][1]
    return None


# Money columns on a holdings spreadsheet. Cover face amounts and premiums
# are parsed as numbers but are never part of צבירה.
SPREADSHEET_MONEY_FIELDS = frozenset({
    'total_balance', 'savings_balance', 'balance', 'tagmulim_balance',
    'severance_balance',
    'management_fee', 'management_fee_savings', 'management_fee_deposits',
    'death_coverage', 'death_lump_sum', 'death_premium',
    'disability_coverage', 'disability_premium',
    'work_disability_coverage', 'work_disability_premium',
    'invalidity_coverage', 'invalidity_premium',
    'waiver_coverage', 'waiver_premium',
    'survivors_coverage', 'survivors_premium',
    'ltc_coverage', 'ltc_premium',
    'coverage_amount', 'monthly_premium', 'last_deposit',
    'track_percent', 'yield_rate',
})

COVER_FACE_FIELDS = (
    'death_lump_sum', 'death_coverage', 'disability_coverage', 'work_disability_coverage',
    'invalidity_coverage', 'waiver_coverage', 'survivors_coverage', 'ltc_coverage',
)

_MONEY_STRIP_RE = re.compile(r'[^0-9.\-]')


def parse_money(value: Any) -> float:
    """Parse a holdings amount. Empty and non-numeric text become 0."""
    if value is None or isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return 0.0
    cleaned = (
        text.replace(',', '')
        .replace('₪', '')
        .replace('%', '')
        .replace('ש"ח', '')
        .replace('ש״ח', '')
        .replace('$', '')
        .replace('€', '')
    )
    cleaned = _MONEY_STRIP_RE.sub('', cleaned)
    if cleaned in {'', '-', '.', '-.'}:
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def account_accumulation(account: Dict[str, Any]) -> float:
    """צבירה for one holdings row.

    An explicit official total (XML ``TOTAL-CHISACHON`` or a ``סה״כ צבירה``
    column) wins. Otherwise the spreadsheet ``סה"כ חיסכון`` column
    (``savings_balance``) is the accumulation. Bare ``יתרה`` is only a
    fallback. Cover amounts, premiums, תגמולים and פיצויים are never added.
    """
    if not isinstance(account, dict):
        return 0.0
    total = parse_money(account.get('total_balance'))
    if total > 0:
        return total
    savings = parse_money(account.get('savings_balance'))
    if savings > 0:
        return savings
    return parse_money(account.get('balance'))


def tagmulim_amount(account: Dict[str, Any]) -> float:
    """תגמולים only. A ``סה"כ חיסכון`` figure is not relabelled as tagmulim."""
    if not isinstance(account, dict):
        return 0.0
    explicit = parse_money(account.get('tagmulim_balance'))
    if explicit > 0:
        return explicit
    total = parse_money(account.get('total_balance'))
    savings = parse_money(account.get('savings_balance'))
    # XML stores the tagmulim component on savings_balance beside the official total.
    if total > 0 and 0 < savings <= total + 0.01:
        return savings
    return 0.0


def deduped_sum(accounts, value_fn) -> float:
    """Same policy: identical rounded amounts count once; distinct slices sum.

    Investment-track rows often repeat the policy-level ``סה"כ חיסכון``.
    Counting that repeated figure once keeps צבירות from doubling. Different
    amounts on the same policy are track slices and are added.
    """
    grouped: Dict[str, Dict[float, float]] = {}
    loose = 0.0
    for account in accounts or []:
        if not isinstance(account, dict):
            continue
        amount = parse_money(value_fn(account))
        if amount <= 0:
            continue
        policy = str(account.get('policy_number') or '').strip()
        rounded = round(amount, 2)
        if not policy:
            loose += rounded
            continue
        grouped.setdefault(policy, {})[rounded] = rounded
    total = loose + sum(sum(bucket.values()) for bucket in grouped.values())
    return round(total, 2)


def accumulation_by(accounts, key_fn) -> Dict[str, float]:
    """Deduped צבירה grouped by ``key_fn(account)`` (provider, product, …)."""
    grouped: Dict[Tuple[str, str], Dict[float, float]] = {}
    loose: Dict[str, float] = {}
    for account in accounts or []:
        if not isinstance(account, dict):
            continue
        amount = account_accumulation(account)
        if amount <= 0:
            continue
        label = str(key_fn(account) or '').strip() or 'לא ידוע'
        policy = str(account.get('policy_number') or '').strip()
        rounded = round(amount, 2)
        if policy:
            grouped.setdefault((label, policy), {})[rounded] = rounded
        else:
            loose[label] = loose.get(label, 0.0) + rounded
    totals: Dict[str, float] = {}
    for (label, _policy), bucket in grouped.items():
        totals[label] = totals.get(label, 0.0) + sum(bucket.values())
    for label, amount in loose.items():
        totals[label] = totals.get(label, 0.0) + amount
    return {label: round(amount, 2) for label, amount in totals.items()}


def accumulation_by_provider(accounts) -> Dict[str, float]:
    return accumulation_by(accounts, lambda account: account.get('provider'))


def cover_face_total(accounts) -> float:
    """Sum uploaded cover face amounts. Premiums are not included."""
    total = 0.0
    for field in COVER_FACE_FIELDS:
        total += deduped_sum(accounts, lambda account, field=field: account.get(field))
    return round(total, 2)


def unique_policy_count(accounts) -> int:
    """Count policies, not repeated investment-track rows of the same policy."""
    seen = set()
    count = 0
    for account in accounts or []:
        if not isinstance(account, dict):
            continue
        policy = str(account.get('policy_number') or '').strip()
        if policy:
            if policy in seen:
                continue
            seen.add(policy)
        count += 1
    return count


PENSION_TABULAR_INDICATORS = (
    'יצרן', 'פוליסה', 'צבירה', 'יתרה', 'תגמולים', 'פיצויים',
    'קופה', 'פנסיה', 'ביטוח', 'גמל', 'חיסכון', 'קרן', 'ת.ז', 'תעודת',
)


def looks_like_pension_table(columns) -> bool:
    """True when headers look like a Swiftness/Mislaka holdings export."""
    for col in columns or []:
        normalized = normalize_hebrew_header(str(col)).lower()
        if any(indicator in normalized or indicator in str(col) for indicator in PENSION_TABULAR_INDICATORS):
            return True
    return False


__all__ = [
    'MislakaSchemaMapping', 'CompiledFields', 'tag_variants',
    'HEBREW_COLUMN_FIELDS', 'normalize_hebrew_header', 'map_hebrew_column',
    'looks_like_pension_table', 'PENSION_TABULAR_INDICATORS',
    'SPREADSHEET_MONEY_FIELDS', 'COVER_FACE_FIELDS', 'DEATH_LUMP_SUM_LABEL', 'parse_money',
    'account_accumulation', 'tagmulim_amount', 'deduped_sum',
    'accumulation_by', 'accumulation_by_provider', 'cover_face_total',
    'unique_policy_count',
]
