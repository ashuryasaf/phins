"""Mislaka (מסלקה) schema mappings — field names, interface / product / status
codes from the official XSD schemas — plus the lookup tables the parsers use.

Moved verbatim from ``services/pension_data_agent.py`` (B5). The tag-variant
tables at the bottom are precompiled once at import so the XML parser never
recomputes hyphen-stripped or CamelCase spellings per element.
"""

from typing import Dict, Tuple


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
        'MISPAR-ZIHUY-MITPATZEACH': 'id_number',
        'MisparZihuiMitpatcheach': 'id_number',
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
        
        # Balances
        'SALDO': 'total_balance',
        'Saldo': 'total_balance',
        'YITRA-KOLELET': 'total_balance',
        'YitraKolelet': 'total_balance',
        'YITROT': 'total_balance',
        'Yitrot': 'total_balance',
        'SCHUM-HATZBARA': 'total_balance',
        'SchumHatzbara': 'total_balance',
        'YITRA-CHISACHON': 'savings_balance',
        'YitraChisachon': 'savings_balance',
        'YITRA-PITZUIM': 'severance_balance',
        'YitraPitzuim': 'severance_balance',
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
        'KISUY-NECHUT': 'disability_coverage',
        'KisuyNechut': 'disability_coverage',
        
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
        'death_coverage', 'disability_coverage',
    })
    CONTRIBUTION_NUMERIC = frozenset({
        'employee_amount', 'employer_amount', 'severance_amount', 'total_amount', 'salary_base',
    })
    SEVERANCE_NUMERIC = frozenset({
        'total_severance', 'available_severance', 'section14_amount', 'section14_percentage',
    })
    TRUTHY = frozenset({'1', 'כן', 'true', 'True', 'Y', 'yes'})


__all__ = ['MislakaSchemaMapping', 'CompiledFields', 'tag_variants']
