"""Mislaka (מסלקה) schema mappings — field names, interface / product / status
codes from the official XSD schemas — plus the lookup tables the parsers use.

Moved verbatim from ``services/pension_data_agent.py`` (B5). The tag-variant
tables at the bottom are precompiled once at import so the XML parser never
recomputes hyphen-stripped or CamelCase spellings per element.
"""

import re
from typing import Any, Dict, List, Optional, Tuple


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
        # Official Mislaka "סכום חד פעמי" on a death-cover / account block.
        'SCHUM-HAD-PEAMI': 'death_coverage',
        'SchumHadPeami': 'death_coverage',
        'SCHUM-KISUY-HAD-PEAMI': 'death_coverage',
        'SchumKisuyHadPeami': 'death_coverage',
        'SCHUM-HAD-PEAMI-MAVET': 'death_coverage',
        'SchumHadPeamiMavet': 'death_coverage',
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
        'SCHUM-PITZUIM': 'total_severance',
        'SchumPitzuim': 'total_severance',
        'YITRAT-PITZUIM': 'total_severance',
        'YitratPitzuim': 'total_severance',
        'TOTAL-PITZUIM': 'total_severance',
        'TOTAL-CHISACHON-PITZUIM': 'total_severance',
        'KFIFA-PITZUIM': 'total_severance',
        'ITZBARUT-PITZUIM': 'total_severance',
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
        'death_coverage', 'disability_coverage', 'death_premium', 'disability_premium',
        'death_monthly',
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
    'ביטוח למקרה מוות': 'death_coverage',
    'כיסוי למקרה מוות': 'death_coverage',
    'סכום חד פעמי': 'death_coverage',
    'סכום חד-פעמי': 'death_coverage',
    'סכום חד פעמי במקרה מוות': 'death_coverage',
    'סכום חד-פעמי במקרה מוות': 'death_coverage',
    'קצבה חודשית במקרה מוות': 'death_monthly',
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


def normalize_hebrew_header(name: str) -> str:
    """Collapse Swiftness/Mislaka header punctuation so ``סה״כ צבירה`` matches ``סה"כ צבירה``."""
    text = str(name or '').strip().translate(_HEBREW_PUNCT_TRANSLATION)
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


_SUM_HEADER_MARKERS = ('סה"כ', 'סך הכל', 'סך-הכל', 'כולל')
_TZVIRA_HEADER_MARKERS = (
    'צבירה כוללת', 'סה"כ צבירה', 'סך הכל צבירה', 'סכום צבירה', 'סך צבירה',
    'סה"כ חיסכון', 'סך חיסכון', 'סך הכל חיסכון', 'חיסכון צבור',
)


def header_money_role(column_name: str) -> Optional[str]:
    """What an uploaded holdings header is for, before last-column-wins.

    A ``ביטוח חיים`` column is the face. A header that says סה״כ / כולל together
    with that cover is the uploaded sum of צבירה + ביטוח חיים. ``צבירה כוללת``
    stays savings even when a later cover column would otherwise overwrite it.
    """
    normalized = normalize_hebrew_header(column_name)
    if not normalized:
        return None
    if any(word in normalized for word in ('פרמיה', 'עלות', 'דמי ניהול', 'ד"נ')):
        return None
    if 'תגמולים' in normalized:
        return None
    has_sum = any(marker in normalized for marker in _SUM_HEADER_MARKERS)
    has_cover = any(word in normalized for word in ('ביטוח חיים', 'כיסוי', 'מוות', 'סכום ביטוח'))
    has_tzvira = 'צבירה' in normalized or 'חיסכון' in normalized
    if 'פיצויים' in normalized or 'פיצויי' in normalized:
        return 'severance_total' if has_sum else 'severance_part'
    if has_cover and (has_sum or (has_tzvira and ('וביטוח' in normalized or 'וכיסוי' in normalized))):
        return 'death_sum'
    if any(marker in normalized for marker in ('סכום חד פעמי', 'למקרה מוות', 'כיסוי מוות')):
        return 'death_face'
    if 'ביטוח חיים' in normalized:
        return 'death_face'
    if any(marker in normalized for marker in _TZVIRA_HEADER_MARKERS) or (has_tzvira and not has_cover):
        return 'tzvira'
    if 'ערך פדיון' in normalized:
        return 'pidyon'
    if 'יתרה' in normalized:
        return 'yitra'
    return None


def note_spreadsheet_value(account: Dict[str, Any], header: str, mapped_name: str, value: Any) -> None:
    """Record one uploaded cell. Cover and צבירה are reconciled in ``finalize_uploaded_amounts``."""
    amount = parse_money(value)
    role = header_money_role(header)
    if role:
        account.setdefault('_money_notes', []).append((role, amount))
        return
    if mapped_name in {'total_balance', 'savings_balance', 'balance', 'death_coverage', 'severance_balance'}:
        account.setdefault('_money_notes', []).append((mapped_name, amount))
        return
    if mapped_name in SPREADSHEET_MONEY_FIELDS:
        account[mapped_name] = amount
        return
    account[mapped_name] = value


def _sum_distinct_pots(amounts: List[float]) -> float:
    """Add פיצויים pots. The same amount repeated on one row counts once."""
    kept: List[float] = []
    for amount in amounts:
        value = parse_money(amount)
        if value <= 0:
            continue
        if any(money_close(value, seen) for seen in kept):
            continue
        kept.append(value)
    return round(sum(kept), 2)


def finalize_uploaded_amounts(account: Dict[str, Any]) -> None:
    """Split uploaded צבירה כוללת from ביטוח חיים and sum every פיצויים column."""
    notes = account.pop('_money_notes', None) or []
    if not notes:
        return
    tzvira = [amount for role, amount in notes if role == 'tzvira' and amount > 0]
    pidyon = [amount for role, amount in notes if role in {'pidyon', 'total_balance', 'savings_balance'} and amount > 0]
    ledgers = [amount for role, amount in notes if role in {'yitra', 'balance'} and amount > 0]
    faces = [amount for role, amount in notes if role in {'death_face', 'death_coverage'} and amount > 0]
    sums = [amount for role, amount in notes if role == 'death_sum' and amount > 0]
    sev_parts = [amount for role, amount in notes if role == 'severance_part' and amount > 0]
    sev_totals = [amount for role, amount in notes if role in {'severance_total', 'severance_balance'} and amount > 0]

    ledger = ledgers[0] if ledgers else 0.0
    combined = max(sums) if sums else 0.0
    # A later cover column can be the uploaded sum (צבירה + ביטוח חיים) even
    # when its header does not say סה״כ. Drop any "face" that is that sum.
    bare_faces = []
    for candidate in faces:
        is_sum = False
        for other in faces + ([combined] if combined else []):
            if money_close(candidate, other):
                continue
            if any(money_close(candidate, savings + other) for savings in tzvira + pidyon):
                is_sum = True
                combined = max(combined, candidate)
                break
            if ledger and any(money_close(candidate, savings + ledger) for savings in tzvira + pidyon):
                is_sum = True
                combined = max(combined, candidate)
                break
        if not is_sum:
            bare_faces.append(candidate)
    death = bare_faces[0] if bare_faces else 0.0
    if not death and combined and ledger and combined > ledger + _MONEY_EPS:
        death = ledger

    accum = 0.0
    for candidate in tzvira:
        if death and money_close(candidate, death):
            continue
        if combined and death and money_close(combined, candidate + death):
            accum = candidate
            break
        if not accum:
            accum = candidate
    if not accum:
        for candidate in pidyon:
            if death and money_close(candidate, death):
                continue
            accum = candidate
            break

    if death and combined and combined > death + _MONEY_EPS:
        if not accum:
            accum = round(combined - death, 2)
        death_value = death
    elif death and accum and ledger and money_close(death, accum + ledger) and ledger > accum + _MONEY_EPS:
        # The ביטוח חיים cell is the uploaded sum; יתרה is the face.
        death_value = ledger
    elif combined and not death and accum and combined > accum + _MONEY_EPS:
        death_value = round(combined - accum, 2)
    else:
        death_value = death or combined

    if accum > 0:
        account['savings_balance'] = accum
        account['total_balance'] = accum
    if ledger > 0:
        account['balance'] = ledger
    if death_value > 0:
        account['death_coverage'] = death_value

    part_sum = _sum_distinct_pots(sev_parts)
    if sev_totals:
        official = max(sev_totals)
        if part_sum <= 0 or money_close(official, part_sum):
            account['severance_balance'] = official
        else:
            account['severance_balance'] = max(official, part_sum)
    elif part_sum > 0:
        account['severance_balance'] = part_sum


# Money columns on a holdings spreadsheet. Cover face amounts and premiums
# are parsed as numbers but are never part of צבירה.
SPREADSHEET_MONEY_FIELDS = frozenset({
    'total_balance', 'savings_balance', 'balance', 'tagmulim_balance',
    'severance_balance',
    'management_fee', 'management_fee_savings', 'management_fee_deposits',
    'death_coverage', 'death_premium', 'death_monthly',
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
    'death_coverage', 'disability_coverage', 'work_disability_coverage',
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


# Official concentrated-report footer labels. A row titled סה״כ / צבירה כוללת
# is the already-summed affiliated total, not another holding.
_SUMMARY_ROW_LABELS = frozenset({
    'סה"כ', 'סה״כ', 'סהכ', 'סך הכל', 'סך-הכל', 'סךהכל',
    'total', 'totals', 'grand total', 'grandtotal',
    'צבירה כוללת', 'סה"כ צבירה', 'סה״כ צבירה', 'סך צבירה',
    'סיכום', 'סיכום כולל',
})
_SUMMARY_ROW_COMPACT = frozenset(
    label.lower().replace(' ', '') for label in _SUMMARY_ROW_LABELS
)


_ACCOUNT_IDENTITY_KEYS = (
    'policy_number', 'provider', 'product_type', 'product_type_name', 'product_name',
    'employer_name', 'employer_id',
)
_RISK_ONLY_FAMILIES = frozenset({
    'ביטוח חיים', 'ביטוח ריסק', 'ביטוח אובדן כושר עבודה',
})
_CENTRAL_SEVERANCE_FAMILY = 'קופה מרכזית לפיצויים'
_MONEY_EPS = 0.021


def money_close(left: Any, right: Any, eps: float = _MONEY_EPS) -> bool:
    """True when two holdings amounts are the same to the affiliated report's ore."""
    return abs(parse_money(left) - parse_money(right)) < eps


def _row_has_money(account: Dict[str, Any]) -> bool:
    for key in (
        'total_balance', 'savings_balance', 'balance', 'tagmulim_balance',
        'severance_balance', 'employer_severance', 'death_coverage',
        'coverage_amount',
    ):
        if parse_money(account.get(key)) > 0:
            return True
    return False


def is_holdings_summary_row(account: Any) -> bool:
    """True for a דוח מרוכז footer (סה״כ / צבירה כוללת), not a real policy."""
    if not isinstance(account, dict):
        return False
    saw_identity = False
    for key in _ACCOUNT_IDENTITY_KEYS:
        raw = str(account.get(key) or '').strip()
        if not raw:
            continue
        saw_identity = True
        compact = normalize_hebrew_header(raw).lower().replace(' ', '')
        if raw in _SUMMARY_ROW_LABELS or compact in _SUMMARY_ROW_COMPACT:
            return True
    if saw_identity:
        return False
    return _row_has_money(account)


def is_pension_account_row(account: Any) -> bool:
    """True for a real holding or employer פיצויים row, not a footer."""
    if not isinstance(account, dict) or is_holdings_summary_row(account):
        return False
    if any(str(account.get(key) or '').strip() for key in _ACCOUNT_IDENTITY_KEYS):
        return _row_has_money(account) or bool(
            account.get('provider') or account.get('policy_number')
        )
    return False


def _raw_savings_candidate(account: Dict[str, Any]) -> float:
    total = parse_money(account.get('total_balance'))
    if total > 0:
        return total
    savings = parse_money(account.get('savings_balance'))
    if savings > 0:
        return savings
    return parse_money(account.get('balance'))


def _is_risk_only_product(account: Dict[str, Any]) -> bool:
    family = product_family_label(account)
    if family in _RISK_ONLY_FAMILIES:
        savings = parse_money(account.get('savings_balance'))
        tagmulim = parse_money(account.get('tagmulim_balance'))
        severance = parse_money(account.get('severance_balance'))
        if savings <= 0 and tagmulim <= 0 and severance <= 0:
            return True
        death = parse_money(account.get('death_coverage'))
        if death > 0 and savings > 0 and money_close(savings, death) and tagmulim <= 0:
            return True
    return False


def _candidate_is_cover_face(account: Dict[str, Any], candidate: float, death: float = 0.0) -> bool:
    """True when SALDO / יתרה / סה״כ is the life-cover face, not חיסכון."""
    if candidate <= 0:
        return False
    if death <= 0:
        death = death_lump_sum(account)
    cover = parse_money(account.get('coverage_amount'))
    matches_death = death > 0 and money_close(candidate, death)
    matches_cover = cover > 0 and money_close(candidate, cover)
    if not (matches_death or matches_cover):
        return False
    savings = parse_money(account.get('savings_balance'))
    tagmulim = parse_money(account.get('tagmulim_balance'))
    severance = parse_money(account.get('severance_balance'))
    if savings > 0 and not money_close(savings, candidate) and not money_close(savings, death):
        return False
    if tagmulim > 0 and not money_close(tagmulim, candidate) and not money_close(tagmulim, death):
        return False
    if severance > 0 and not money_close(severance, candidate) and not money_close(severance, death):
        return False
    return True


def apply_uploaded_product_type(account: Dict[str, Any]) -> None:
    """Keep the file's סוג מוצר / SHEM-MUTZAR when that text names a product."""
    if not isinstance(account, dict):
        return
    uploaded = str(account.get('product_type') or '').strip()
    shem = str(account.get('product_name') or '').strip()
    if uploaded and not uploaded.isdigit() and _family_from_text(uploaded):
        account['product_type_name'] = uploaded
        return
    if shem and not shem.isdigit() and _family_from_text(shem):
        if not uploaded or uploaded.isdigit() or not _family_from_text(uploaded):
            account['product_type_name'] = shem


def apply_component_severance(account: Dict[str, Any], component_amounts: List[float]) -> None:
    """Keep every distinct code-3 פיצויים pot, including ones above YITRAT-PITZUIM."""
    if not isinstance(account, dict):
        return
    component = _sum_distinct_pots(component_amounts)
    existing = parse_money(account.get('severance_balance'))
    if component > existing + _MONEY_EPS:
        account['severance_balance'] = component
    elif existing <= 0 and component > 0:
        account['severance_balance'] = component


def stamp_account_accumulation(account: Dict[str, Any]) -> float:
    """Write official צבירה כוללת / ביטוח חיים so cover face never lands on savings."""
    if not isinstance(account, dict):
        return 0.0
    apply_uploaded_product_type(account)
    death = death_lump_sum(account)
    raw_total = parse_money(account.get('total_balance'))
    explicit_death = parse_money(account.get('death_coverage'))
    if death > 0:
        account['death_coverage'] = death
    elif explicit_death > 0:
        account['death_coverage'] = 0.0
    account['product_type_display'] = product_type_display(account)
    amount = account_accumulation(account)
    if amount > 0:
        if raw_total <= 0:
            # Stamped from סה"כ חיסכון / יתרה, so the row never carried a
            # תגמולים split and tagmulim_amount must not read one into it.
            account['accumulation_from_savings'] = True
        account['total_balance'] = amount
    elif raw_total > 0 and _candidate_is_cover_face(account, raw_total, death=death):
        account['total_balance'] = 0.0
    return amount


def holdings_accounts(accounts) -> List[Dict[str, Any]]:
    """Real holdings rows with צבירה כוללת stamped; summary footers dropped."""
    material: List[Dict[str, Any]] = []
    for account in accounts or []:
        if not isinstance(account, dict) or is_holdings_summary_row(account):
            continue
        stamp_account_accumulation(account)
        material.append(account)
    return material


def account_accumulation(account: Dict[str, Any]) -> float:
    """צבירה כוללת for one holdings row.

    An explicit official total (XML ``TOTAL-CHISACHON`` or a ``סה״כ צבירה`` /
    ``צבירה כוללת`` column) wins. Otherwise the spreadsheet ``סה"כ חיסכון``
    column (``savings_balance``) is the accumulation. Bare ``יתרה`` is only a
    fallback, and never when it equals the death-cover face. Cover amounts,
    premiums, תגמולים and פיצויים are never added.
    """
    if not isinstance(account, dict):
        return 0.0
    death = death_lump_sum(account)
    savings = parse_money(account.get('savings_balance'))
    total = parse_money(account.get('total_balance'))
    yitra = parse_money(account.get('balance'))
    if death > 0 and savings > 0 and total > 0 and money_close(total, death) and not money_close(savings, death):
        return savings
    if death > 0 and savings > 0 and total > 0 and money_close(total, savings + death):
        return savings
    if total > 0 and not _candidate_is_cover_face(account, total, death=death):
        return total
    if savings > 0 and not _candidate_is_cover_face(account, savings, death=death):
        return savings
    if yitra > 0 and not _candidate_is_cover_face(account, yitra, death=death):
        return yitra
    return 0.0


def tagmulim_amount(account: Dict[str, Any]) -> float:
    """תגמולים only. A ``סה"כ חיסכון`` figure is not relabelled as tagmulim."""
    if not isinstance(account, dict):
        return 0.0
    explicit = parse_money(account.get('tagmulim_balance'))
    if explicit > 0:
        return explicit
    if account.get('accumulation_from_savings'):
        return 0.0
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
        if not isinstance(account, dict) or is_holdings_summary_row(account):
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
        if not isinstance(account, dict) or is_holdings_summary_row(account):
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


# Official Mislaka "ריכוז סכומי הצבירה לפי סוגי המוצרים" buckets. Codes 1–3
# are pension-fund variants and collapse to one קרן פנסיה line, matching the
# concentrated clearinghouse report rather than the 12 raw SUG-MUTZAR labels.
PRODUCT_FAMILY_BY_CODE = {
    '1': 'קרן פנסיה',
    '2': 'קרן פנסיה',
    '3': 'קרן פנסיה',
    '4': 'קופת גמל',
    '5': 'קופה מרכזית לפיצויים',
    '6': 'קרן השתלמות',
    '7': 'ביטוח מנהלים',
    '8': 'ביטוח חיים',
    '9': 'ביטוח פנסיוני',
    '10': 'פוליסת חיסכון',
    '11': 'ביטוח ריסק',
    '12': 'ביטוח אובדן כושר עבודה',
}

# Longer needles first so "קופת גמל להשקעה" and "משולב חיסכון" win.
_PRODUCT_FAMILY_ALIASES = (
    (('קופת גמל להשקעה', 'גמל להשקעה'), 'קופת גמל להשקעה'),
    (('קופה מרכזית', 'מרכזית לפיצויים'), 'קופה מרכזית לפיצויים'),
    (('משולב חיסכון', 'ביטוח מנהלים', 'מנהלים ושכירים', 'managers insurance'), 'ביטוח מנהלים'),
    (('סיכון טהור', 'ביטוח סיכונים', 'ביטוח ריסק', 'ריסק', 'risk insurance'), 'ביטוח ריסק'),
    (('חיסכון טהור', 'חיסכון פיננסי', 'פוליסת חיסכון', 'savings policy'), 'פוליסת חיסכון'),
    (('קרן פנסיה', 'פנסיה מקיפה', 'פנסיה חדשה', 'פנסיה כללית', 'פנסיה ותיקה', 'pension fund', 'pension'), 'קרן פנסיה'),
    (('קופת גמל', 'קופות גמל', 'provident', 'gemel'), 'קופת גמל'),
    (('קרן השתלמות', 'השתלמות', 'education fund'), 'קרן השתלמות'),
    (('אובדן כושר', 'אבדן כושר', 'disability insurance'), 'ביטוח אובדן כושר עבודה'),
    (('ביטוח חיים משכנתא', 'משכנתא', 'ביטוח יסודי', 'ביטוח חיים', 'life insurance'), 'ביטוח חיים'),
)


def _family_from_text(text: str) -> str:
    blob = str(text or '').strip().lower()
    if not blob:
        return ''
    for needles, family in _PRODUCT_FAMILY_ALIASES:
        if any(needle.lower() in blob for needle in needles):
            return family
    return ''


def product_family_label(account: Any, unknown: str = 'לא ידוע') -> str:
    """Official concentrated-report product family for one holdings row.

    A Hebrew ``סוג מוצר`` / ``SHEM-MUTZAR`` from the file wins over a numeric
    code, so a code-table mismatch cannot relabel the policy.
    """
    if not isinstance(account, dict):
        return unknown
    for key in ('product_type', 'product_type_name'):
        raw = str(account.get(key) or '').strip()
        if raw and not raw.isdigit() and raw not in PRODUCT_FAMILY_BY_CODE:
            family = _family_from_text(raw)
            if family:
                return family
    for raw in (account.get('product_type_code'), account.get('product_type')):
        code = str(raw or '').strip()
        if code in PRODUCT_FAMILY_BY_CODE:
            return PRODUCT_FAMILY_BY_CODE[code]
    raw_type = str(account.get('product_type') or '').strip()
    raw_name = str(account.get('product_type_name') or '').strip()
    for candidate in (raw_type, raw_name):
        for code, info in MislakaSchemaMapping.PRODUCT_TYPE_CODES.items():
            if candidate in {info.get('he', ''), info.get('en', ''), info.get('name', '')}:
                return PRODUCT_FAMILY_BY_CODE.get(code, info.get('he') or unknown)
    # No type text: the plan name is only a fallback, never an override.
    for candidate in (raw_name, str(account.get('product_name') or '').strip()):
        family = _family_from_text(candidate)
        if family:
            return family
    return raw_name or raw_type or unknown


def product_type_display(account: Any, unknown: str = 'לא ידוע') -> str:
    """סוג מוצר as the file wrote it, when that text is a real product type."""
    if not isinstance(account, dict):
        return unknown
    for key in ('product_type_name', 'product_type'):
        raw = str(account.get(key) or '').strip()
        if raw and not raw.isdigit() and _family_from_text(raw):
            return raw
    return product_family_label(account, unknown=unknown)


def accumulation_by_product(accounts) -> Dict[str, float]:
    """Deduped צבירה grouped the way the official Mislaka report groups it."""
    return accumulation_by(accounts, product_family_label)


def _cover_looks_like_death(item: Dict[str, Any]) -> bool:
    code = str(item.get('code') or '').strip()
    if code in {'1', '01'}:
        return True
    name = str(item.get('name') or '')
    lowered = name.lower()
    return (
        'מוות' in name
        or 'חיים' in name
        or 'death' in lowered
        or 'life' in lowered
    )


def _is_genuine_death_cover(item: Dict[str, Any]) -> bool:
    """Kisuy that carries סכום חד פעמי, not סכום ביטוח כולל (cash + face)."""
    if not isinstance(item, dict):
        return False
    code = str(item.get('code') or '').strip()
    name = str(item.get('name') or '')
    lowered = name.lower()
    if item.get('had_peami'):
        return True
    if code in {'1', '01'}:
        return True
    return 'מוות' in name or 'death' in lowered


def _death_from_risk_covers(account: Dict[str, Any]) -> float:
    total = 0.0
    seen: set = set()
    for item in account.get('risk_covers') or []:
        if not isinstance(item, dict) or not _is_genuine_death_cover(item):
            continue
        lump = parse_money(item.get('amount'))
        if lump <= 0:
            continue
        key = (str(item.get('code') or ''), str(item.get('name') or ''), round(lump, 2))
        if key in seen:
            continue
        seen.add(key)
        total += lump
    return total


def death_lump_sum(account: Dict[str, Any]) -> float:
    """סכום חד פעמי for death cover on one holdings row.

    Prefers a genuine Kisuy lump (``SCHUM-HAD-PEAMI`` / code 1 / מוות).
    Account-level ``ביטוח חיים`` is used when it is not the savings figure
    and not ``צבירה + כיסוי``. Monthly death annuity is never added.
    """
    if not isinstance(account, dict):
        return 0.0
    from_covers = _death_from_risk_covers(account)
    explicit = parse_money(account.get('death_coverage'))
    savings = parse_money(account.get('savings_balance'))
    total = parse_money(account.get('total_balance'))
    yitra = parse_money(account.get('balance'))
    cover = parse_money(account.get('coverage_amount'))
    official_savings = 0.0
    if savings > 0:
        official_savings = savings
    elif total > 0 and not (explicit > 0 and money_close(total, explicit)):
        official_savings = total

    if from_covers > 0:
        if explicit > 0 and official_savings > 0 and money_close(explicit, official_savings + from_covers):
            return from_covers
        return from_covers

    if explicit <= 0:
        return 0.0
    if official_savings > 0 and money_close(explicit, official_savings):
        if _is_risk_only_product(account):
            return explicit
        return 0.0
    if savings > 0 and total > 0 and explicit > 0 and money_close(explicit, savings + total) and not money_close(savings, total):
        # Uploaded ביטוח חיים is צבירה + כיסוי. The other total is the face.
        return total if total < explicit else savings
    if official_savings > 0 and explicit > official_savings + _MONEY_EPS:
        remainder = round(explicit - official_savings, 2)
        if (
            (yitra > 0 and money_close(remainder, yitra))
            or (cover > 0 and money_close(remainder, cover))
            or (total > 0 and money_close(remainder, total) and not money_close(total, official_savings))
        ):
            return remainder
    return explicit


def account_severance(account: Dict[str, Any]) -> float:
    """פיצויים for one holdings row, including type-5 central funds."""
    if not isinstance(account, dict):
        return 0.0
    explicit = parse_money(account.get('severance_balance'))
    employer = parse_money(account.get('employer_severance'))
    pots = 0.0
    for pot in account.get('severance_pots') or []:
        if isinstance(pot, dict):
            pots += parse_money(pot.get('severance_balance') or pot.get('amount'))
    family = product_family_label(account)
    if family == _CENTRAL_SEVERANCE_FAMILY or str(account.get('product_type_code') or '').strip() == '5':
        return max(explicit, employer, pots, account_accumulation(account))
    if explicit > 0 and employer > 0 and money_close(explicit, employer):
        return explicit + pots
    return explicit + employer + pots


def severance_sum(accounts, extra_severance: Any = 0) -> float:
    """Sum affiliated פיצויים. Same employer+policy+amount counts once; pots add."""
    grouped: Dict[Tuple[str, str], Dict[float, float]] = {}
    loose = 0.0
    for account in accounts or []:
        if not isinstance(account, dict) or is_holdings_summary_row(account):
            continue
        amount = account_severance(account)
        if amount <= 0:
            continue
        policy = str(account.get('policy_number') or '').strip()
        employer = str(account.get('employer_name') or account.get('employer_id') or '').strip()
        rounded = round(amount, 2)
        if not policy and not employer:
            loose += rounded
            continue
        grouped.setdefault((policy, employer), {})[rounded] = rounded
    holdings = loose + sum(sum(bucket.values()) for bucket in grouped.values())
    extra = parse_money(extra_severance)
    if extra > 0 and not money_close(extra, holdings):
        holdings += extra
    return round(holdings, 2)


_MAX_MERGE_AMOUNT_FIELDS = frozenset({
    'total_balance', 'savings_balance', 'balance', 'tagmulim_balance',
    'death_coverage', 'disability_coverage', 'coverage_amount',
    'work_disability_coverage', 'invalidity_coverage', 'waiver_coverage',
    'survivors_coverage', 'ltc_coverage',
    'death_premium', 'disability_premium', 'work_disability_premium',
    'invalidity_premium', 'waiver_premium', 'survivors_premium', 'ltc_premium',
    'monthly_premium', 'last_deposit', 'track_percent', 'yield_rate',
    'management_fee', 'management_fee_savings', 'management_fee_deposits',
})


def merge_holdings_account(existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    """Collapse XML + concentrated views of one policy without dropping פיצויים pots."""
    exist_emp = str(existing.get('employer_name') or existing.get('employer_id') or '').strip()
    new_emp = str(incoming.get('employer_name') or incoming.get('employer_id') or '').strip()
    for field, value in incoming.items():
        if field in {'severance_balance', 'employer_severance'}:
            exist_amt = parse_money(existing.get(field))
            new_amt = parse_money(value)
            if exist_emp and new_emp and exist_emp != new_emp and exist_amt > 0 and new_amt > 0:
                pots = list(existing.get('severance_pots') or [])
                pots.append({'employer_name': new_emp, 'severance_balance': new_amt})
                existing['severance_pots'] = pots
            else:
                existing[field] = max(exist_amt, new_amt)
        elif field == 'severance_pots' and value:
            existing[field] = list(existing.get(field) or []) + list(value or [])
        elif field in _MAX_MERGE_AMOUNT_FIELDS:
            existing[field] = max(parse_money(existing.get(field)), parse_money(value))
        elif value not in (None, '') and (
            not existing.get(field)
            or (field in {'product_type', 'product_type_name'} and str(existing.get(field)).isdigit())
        ):
            existing[field] = value
    stamp_account_accumulation(existing)
    return existing


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
        if not isinstance(account, dict) or is_holdings_summary_row(account):
            continue
        policy = str(account.get('policy_number') or '').strip()
        if policy:
            if policy in seen:
                continue
            seen.add(policy)
        count += 1
    return count


def portfolio_totals(accounts, extra_severance: Any = 0) -> Dict[str, Any]:
    """One affiliated snapshot: stamped צבירה כוללת, product families, integrity."""
    material = holdings_accounts(accounts)
    total_balance = deduped_sum(material, account_accumulation)
    total_savings = deduped_sum(material, lambda account: account.get('savings_balance'))
    total_tagmulim = deduped_sum(material, tagmulim_amount)
    total_yitra = deduped_sum(material, lambda account: account.get('balance'))
    total_severance = severance_sum(material, extra_severance=extra_severance)
    by_provider = accumulation_by_provider(material)
    by_product = accumulation_by_product(material)
    product_sum = round(sum(by_product.values()), 2)
    providers = sorted({
        str(account.get('provider') or '').strip()
        for account in material
        if str(account.get('provider') or '').strip()
    })
    return {
        'total_balance': total_balance,
        'total_savings': total_savings,
        'total_tagmulim': total_tagmulim,
        'total_yitra': total_yitra,
        'total_severance': total_severance,
        'total_coverage': cover_face_total(material),
        'total_death_lump_sum': deduped_sum(material, death_lump_sum),
        'by_provider': by_provider,
        'by_product': by_product,
        'account_count': unique_policy_count(material),
        'provider_count': len(providers),
        'providers': providers,
        'integrity': {
            'product_sum': product_sum,
            'accumulation_reconciles': abs(product_sum - total_balance) < 0.021,
            'yitra_excluded': total_yitra <= 0 or abs(total_balance - total_yitra) > 0.021,
            'summary_rows_excluded': True,
        },
    }


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
    'SPREADSHEET_MONEY_FIELDS', 'COVER_FACE_FIELDS', 'parse_money',
    'account_accumulation', 'stamp_account_accumulation', 'holdings_accounts',
    'is_holdings_summary_row', 'is_pension_account_row', 'tagmulim_amount',
    'account_severance', 'severance_sum', 'merge_holdings_account',
    'money_close', 'deduped_sum',
    'accumulation_by', 'accumulation_by_provider', 'accumulation_by_product',
    'product_family_label', 'product_type_display', 'apply_uploaded_product_type',
    'PRODUCT_FAMILY_BY_CODE', 'death_lump_sum',
    'header_money_role', 'note_spreadsheet_value', 'finalize_uploaded_amounts',
    'apply_component_severance',
    'cover_face_total', 'portfolio_totals',
    'unique_policy_count',
]
