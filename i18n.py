"""
PHINS International (i18n) Module
Multi-language support for 20 major world languages
Lightweight, production-ready translation system
"""

from enum import Enum
from typing import Dict, Optional, List
from decimal import Decimal
import json
from datetime import datetime


class Language(Enum):
    """20 most spoken languages in the world"""
    EN = "en"        # English
    ZH = "zh"        # Mandarin Chinese
    HI = "hi"        # Hindi
    ES = "es"        # Spanish
    FR = "fr"        # French
    AR = "ar"        # Arabic
    PT = "pt"        # Portuguese
    RU = "ru"        # Russian
    JA = "ja"        # Japanese
    DE = "de"        # German
    IT = "it"        # Italian
    KO = "ko"        # Korean
    TR = "tr"        # Turkish
    VI = "vi"        # Vietnamese
    NL = "nl"        # Dutch
    PL = "pl"        # Polish
    SV = "sv"        # Swedish
    EL = "el"        # Greek
    HE = "he"        # Hebrew
    ID = "id"        # Indonesian


class TranslationManager:
    """Manages translations and localization across the platform"""
    
    # Core translations dictionary - English base
    TRANSLATIONS = {
        # === UI & General Terms ===
        "app_name": {
            "en": "PHINS Insurance Management",
            "zh": "PHINS保险管理系统",
            "hi": "PHINS बीमा प्रबंधन",
            "es": "PHINS Gestión de Seguros",
            "fr": "PHINS Gestion des Assurances",
            "ar": "إدارة التأمين PHINS",
            "pt": "PHINS Gerenciamento de Seguros",
            "ru": "PHINS Управление Страховкой",
            "ja": "PHINS保険管理",
            "de": "PHINS Versicherungsverwaltung",
            "it": "PHINS Gestione Assicurazioni",
            "ko": "PHINS 보험 관리",
            "tr": "PHINS Sigorta Yönetimi",
            "vi": "PHINS Quản lý Bảo hiểm",
            "nl": "PHINS Verzekeringsbeheer",
            "pl": "PHINS Zarządzanie Ubezpieczeniami",
            "sv": "PHINS Försäkringsförvaltning",
            "el": "PHINS Διαχείριση Ασφαλειών",
            "he": "ניהול ביטוח PHINS",
            "id": "PHINS Manajemen Asuransi"
        },
        
        # === Division Names ===
        "division_sales": {
            "en": "Sales", "zh": "销售", "hi": "बिक्रय", "es": "Ventas",
            "fr": "Ventes", "ar": "المبيعات", "pt": "Vendas", "ru": "Продажи",
            "ja": "営業", "de": "Vertrieb", "it": "Vendite", "ko": "판매",
            "tr": "Satış", "vi": "Bán hàng", "nl": "Verkoop", "pl": "Sprzedaż",
            "sv": "Försäljning", "el": "Πωλήσεις", "he": "מכירות", "id": "Penjualan"
        },
        "division_underwriting": {
            "en": "Underwriting", "zh": "承保", "hi": "हामीदारी", "es": "Suscripción",
            "fr": "Souscription", "ar": "الاكتتاب", "pt": "Subscrição", "ru": "Андеррайтинг",
            "ja": "引受", "de": "Underwriting", "it": "Sottoscrizione", "ko": "인수",
            "tr": "Sigortacılık", "vi": "Cấp phép", "nl": "Underwriting", "pl": "Gwarantowanie",
            "sv": "Försäkringsskrivning", "el": "Ασφάλιση", "he": "הנפקה", "id": "Penjaminan"
        },
        "division_claims": {
            "en": "Claims", "zh": "理赔", "hi": "दावे", "es": "Reclamaciones",
            "fr": "Sinistres", "ar": "المطالبات", "pt": "Sinistros", "ru": "Требования",
            "ja": "請求", "de": "Ansprüche", "it": "Sinistri", "ko": "청구",
            "tr": "Hasar", "vi": "Yêu cầu", "nl": "Schadeclaims", "pl": "Roszczenia",
            "sv": "Skador", "el": "Αξιώσεις", "he": "תביעות", "id": "Klaim"
        },
        "division_accounting": {
            "en": "Accounting", "zh": "会计", "hi": "लेखांकन", "es": "Contabilidad",
            "fr": "Comptabilité", "ar": "المحاسبة", "pt": "Contabilidade", "ru": "Бухгалтерия",
            "ja": "会計", "de": "Buchhaltung", "it": "Contabilità", "ko": "회계",
            "tr": "Muhasebe", "vi": "Kế toán", "nl": "Administratie", "pl": "Rachunkowość",
            "sv": "Bokföring", "el": "Λογιστική", "he": "חשבונאות", "id": "Akuntansi"
        },
        "division_actuarial": {
            "en": "Actuarial", "zh": "精算", "hi": "बीमांकिक", "es": "Actuarial",
            "fr": "Actuarial", "ar": "الخبير الاكتواري", "pt": "Atuarial", "ru": "Актуарный",
            "ja": "保険数理", "de": "Versicherungsmathematik", "it": "Attuariale", "ko": "보험수학",
            "tr": "Aktüeryal", "vi": "Kỹ thuật bảo hiểm", "nl": "Actuariaat", "pl": "Ubezpieczeniowe",
            "sv": "Försäkringsmatematik", "el": "Αναλογιστικό", "he": "אקטואר", "id": "Aktuaria"
        },
        "division_reinsurance": {
            "en": "Reinsurance", "zh": "再保险", "hi": "पुनः बीमा", "es": "Reaseguro",
            "fr": "Réassurance", "ar": "إعادة التأمين", "pt": "Resseguro", "ru": "Перестраховка",
            "ja": "再保険", "de": "Rückversicherung", "it": "Riassicurazione", "ko": "재보험",
            "tr": "Reasürans", "vi": "Tái bảo hiểm", "nl": "Herverzekering", "pl": "Reasekuracja",
            "sv": "Återförsäkring", "el": "Αντασφάλιση", "he": "ביטוח חוזר", "id": "Reasuransi"
        },
        
        # === Status Fields ===
        "status_active": {
            "en": "Active", "zh": "活跃", "hi": "सक्रिय", "es": "Activo",
            "fr": "Actif", "ar": "نشط", "pt": "Ativo", "ru": "Активный",
            "ja": "アクティブ", "de": "Aktiv", "it": "Attivo", "ko": "활성",
            "tr": "Etkin", "vi": "Hoạt động", "nl": "Actief", "pl": "Aktywny",
            "sv": "Aktiv", "el": "Ενεργό", "he": "פעיל", "id": "Aktif"
        },
        "status_pending": {
            "en": "Pending", "zh": "待处理", "hi": "लंबित", "es": "Pendiente",
            "fr": "En attente", "ar": "قيد الانتظار", "pt": "Pendente", "ru": "Ожидающий",
            "ja": "保留中", "de": "Ausstehend", "it": "In sospeso", "ko": "대기중",
            "tr": "Beklemede", "vi": "Chờ xử lý", "nl": "Hangende", "pl": "Oczekujący",
            "sv": "Väntande", "el": "Εκκρεμής", "he": "בהמתנה", "id": "Tertunda"
        },
        "status_approved": {
            "en": "Approved", "zh": "已批准", "hi": "अनुमोदित", "es": "Aprobado",
            "fr": "Approuvé", "ar": "موافق عليه", "pt": "Aprovado", "ru": "Одобрено",
            "ja": "承認済み", "de": "Genehmigt", "it": "Approvato", "ko": "승인됨",
            "tr": "Onaylı", "vi": "Được phê duyệt", "nl": "Goedgekeurd", "pl": "Zatwierdzony",
            "sv": "Godkänd", "el": "Εγκεκριμένο", "he": "אושר", "id": "Disetujui"
        },
        "status_rejected": {
            "en": "Rejected", "zh": "已拒绝", "hi": "अस्वीकृत", "es": "Rechazado",
            "fr": "Rejeté", "ar": "مرفوض", "pt": "Rejeitado", "ru": "Отклонено",
            "ja": "却下", "de": "Abgelehnt", "it": "Rifiutato", "ko": "거부됨",
            "tr": "Reddedildi", "vi": "Bị từ chối", "nl": "Afgewezen", "pl": "Odrzucony",
            "sv": "Avvisad", "el": "Απορρίφθηκε", "he": "נדחה", "id": "Ditolak"
        },
        
        # === Actions ===
        "action_create": {
            "en": "Create", "zh": "创建", "hi": "बनाएं", "es": "Crear",
            "fr": "Créer", "ar": "إنشاء", "pt": "Criar", "ru": "Создать",
            "ja": "作成", "de": "Erstellen", "it": "Crea", "ko": "만들기",
            "tr": "Oluştur", "vi": "Tạo", "nl": "Maken", "pl": "Utwórz",
            "sv": "Skapa", "el": "Δημιουργία", "he": "יצור", "id": "Buat"
        },
        "action_edit": {
            "en": "Edit", "zh": "编辑", "hi": "संपादित करें", "es": "Editar",
            "fr": "Modifier", "ar": "تحرير", "pt": "Editar", "ru": "Редактировать",
            "ja": "編集", "de": "Bearbeiten", "it": "Modifica", "ko": "편집",
            "tr": "Düzenle", "vi": "Chỉnh sửa", "nl": "Bewerken", "pl": "Edycja",
            "sv": "Redigera", "el": "Επεξεργασία", "he": "ערוך", "id": "Ubah"
        },
        "action_delete": {
            "en": "Delete", "zh": "删除", "hi": "हटाएं", "es": "Eliminar",
            "fr": "Supprimer", "ar": "حذف", "pt": "Deletar", "ru": "Удалить",
            "ja": "削除", "de": "Löschen", "it": "Elimina", "ko": "삭제",
            "tr": "Sil", "vi": "Xóa", "nl": "Verwijderen", "pl": "Usuń",
            "sv": "Ta bort", "el": "Διαγραφή", "he": "מחק", "id": "Hapus"
        },
        "action_save": {
            "en": "Save", "zh": "保存", "hi": "सहेजें", "es": "Guardar",
            "fr": "Enregistrer", "ar": "حفظ", "pt": "Salvar", "ru": "Сохранить",
            "ja": "保存", "de": "Speichern", "it": "Salva", "ko": "저장",
            "tr": "Kaydet", "vi": "Lưu", "nl": "Opslaan", "pl": "Zapisz",
            "sv": "Spara", "el": "Αποθήκευση", "he": "שמור", "id": "Simpan"
        },
        "action_view": {
            "en": "View", "zh": "查看", "hi": "देखें", "es": "Ver",
            "fr": "Voir", "ar": "عرض", "pt": "Visualizar", "ru": "Просмотр",
            "ja": "表示", "de": "Ansicht", "it": "Visualizza", "ko": "보기",
            "tr": "Görüntüle", "vi": "Xem", "nl": "Weergave", "pl": "Podgląd",
            "sv": "Visa", "el": "Προβολή", "he": "צפה", "id": "Lihat"
        },
        "action_cancel": {
            "en": "Cancel", "zh": "取消", "hi": "रद्द करें", "es": "Cancelar",
            "fr": "Annuler", "ar": "إلغاء", "pt": "Cancelar", "ru": "Отмена",
            "ja": "キャンセル", "de": "Abbrechen", "it": "Annulla", "ko": "취소",
            "tr": "İptal", "vi": "Hủy", "nl": "Annuleren", "pl": "Anuluj",
            "sv": "Avbryt", "el": "Ακύρωση", "he": "ביטול", "id": "Batal"
        },
        
        # === Common Fields ===
        "field_id": {
            "en": "ID", "zh": "编号", "hi": "आईडी", "es": "ID",
            "fr": "ID", "ar": "معرف", "pt": "ID", "ru": "ID",
            "ja": "ID", "de": "ID", "it": "ID", "ko": "ID",
            "tr": "ID", "vi": "ID", "nl": "ID", "pl": "ID",
            "sv": "ID", "el": "ID", "he": "ID", "id": "ID"
        },
        "field_name": {
            "en": "Name", "zh": "名称", "hi": "नाम", "es": "Nombre",
            "fr": "Nom", "ar": "الاسم", "pt": "Nome", "ru": "Имя",
            "ja": "名前", "de": "Name", "it": "Nome", "ko": "이름",
            "tr": "Ad", "vi": "Tên", "nl": "Naam", "pl": "Nazwa",
            "sv": "Namn", "el": "Όνομα", "he": "שם", "id": "Nama"
        },
        "field_email": {
            "en": "Email", "zh": "电子邮件", "hi": "ईमेल", "es": "Correo",
            "fr": "E-mail", "ar": "بريد إلكتروني", "pt": "Email", "ru": "Электронная почта",
            "ja": "メール", "de": "E-Mail", "it": "Email", "ko": "이메일",
            "tr": "E-posta", "vi": "Email", "nl": "E-mail", "pl": "Email",
            "sv": "E-post", "el": "Email", "he": "אימייל", "id": "Email"
        },
        "field_phone": {
            "en": "Phone", "zh": "电话", "hi": "फोन", "es": "Teléfono",
            "fr": "Téléphone", "ar": "هاتف", "pt": "Telefone", "ru": "Телефон",
            "ja": "電話", "de": "Telefon", "it": "Telefono", "ko": "전화",
            "tr": "Telefon", "vi": "Điện thoại", "nl": "Telefoon", "pl": "Telefon",
            "sv": "Telefon", "el": "Τηλέφωνο", "he": "טלפון", "id": "Telepon"
        },
        "field_address": {
            "en": "Address", "zh": "地址", "hi": "पता", "es": "Dirección",
            "fr": "Adresse", "ar": "عنوان", "pt": "Endereço", "ru": "Адрес",
            "ja": "住所", "de": "Adresse", "it": "Indirizzo", "ko": "주소",
            "tr": "Adres", "vi": "Địa chỉ", "nl": "Adres", "pl": "Adres",
            "sv": "Adress", "el": "Διεύθυνση", "he": "כתובת", "id": "Alamat"
        },
        "field_amount": {
            "en": "Amount", "zh": "金额", "hi": "राशि", "es": "Cantidad",
            "fr": "Montant", "ar": "المبلغ", "pt": "Quantidade", "ru": "Сумма",
            "ja": "金額", "de": "Betrag", "it": "Importo", "ko": "금액",
            "tr": "Tutar", "vi": "Số tiền", "nl": "Bedrag", "pl": "Kwota",
            "sv": "Belopp", "el": "Ποσό", "he": "סכום", "id": "Jumlah"
        },
        "field_date": {
            "en": "Date", "zh": "日期", "hi": "तारीख", "es": "Fecha",
            "fr": "Date", "ar": "تاريخ", "pt": "Data", "ru": "Дата",
            "ja": "日付", "de": "Datum", "it": "Data", "ko": "날짜",
            "tr": "Tarih", "vi": "Ngày", "nl": "Datum", "pl": "Data",
            "sv": "Datum", "el": "Ημερομηνία", "he": "תאריך", "id": "Tanggal"
        },
        "field_status": {
            "en": "Status", "zh": "状态", "hi": "स्थिति", "es": "Estado",
            "fr": "Statut", "ar": "حالة", "pt": "Status", "ru": "Статус",
            "ja": "ステータス", "de": "Status", "it": "Stato", "ko": "상태",
            "tr": "Durum", "vi": "Trạng thái", "nl": "Status", "pl": "Status",
            "sv": "Status", "el": "Κατάσταση", "he": "סטטוס", "id": "Status"
        },
        
        # === Messages ===
        "msg_success": {
            "en": "Operation completed successfully", "zh": "操作成功完成",
            "hi": "ऑपरेशन सफलतापूर्वक पूरा हुआ", "es": "Operación completada con éxito",
            "fr": "Opération effectuée avec succès", "ar": "تمت العملية بنجاح",
            "pt": "Operação concluída com sucesso", "ru": "Операция выполнена успешно",
            "ja": "操作が正常に完了しました", "de": "Vorgang erfolgreich abgeschlossen",
            "it": "Operazione completata con successo", "ko": "작업이 성공적으로 완료되었습니다",
            "tr": "İşlem başarıyla tamamlandı", "vi": "Hoạt động hoàn tất thành công",
            "nl": "Bewerking voltooid", "pl": "Operacja zakończona pomyślnie",
            "sv": "Operationen slutfördes", "el": "Η λειτουργία ολοκληρώθηκε",
            "he": "הפעולה הושלמה בהצלחה", "id": "Operasi berhasil diselesaikan"
        },
        "msg_error": {
            "en": "An error occurred", "zh": "发生错误",
            "hi": "एक त्रुटि हुई", "es": "Ocurrió un error",
            "fr": "Une erreur s'est produite", "ar": "حدث خطأ",
            "pt": "Ocorreu um erro", "ru": "Произошла ошибка",
            "ja": "エラーが発生しました", "de": "Ein Fehler ist aufgetreten",
            "it": "Si è verificato un errore", "ko": "오류가 발생했습니다",
            "tr": "Bir hata oluştu", "vi": "Đã xảy ra lỗi",
            "nl": "Er is een fout opgetreden", "pl": "Pojawił się błąd",
            "sv": "Ett fel uppstod", "el": "Προκύφθηκε σφάλμα",
            "he": "אירעה שגיאה", "id": "Terjadi kesalahan"
        },
        "msg_confirm": {
            "en": "Are you sure?", "zh": "你确定吗?",
            "hi": "क्या आप सुनिश्चित हैं?", "es": "¿Estás seguro?",
            "fr": "Êtes-vous sûr ?", "ar": "هل أنت متأكد؟",
            "pt": "Tem certeza?", "ru": "Вы уверены?",
            "ja": "よろしいですか？", "de": "Bist du sicher?",
            "it": "Sei sicuro?", "ko": "확실합니까?",
            "tr": "Emin misiniz?", "vi": "Bạn có chắc không?",
            "nl": "Weet je het zeker?", "pl": "Jesteś pewny?",
            "sv": "Är du säker?", "el": "Είστε σίγουρος;",
            "he": "האם אתה בטוח?", "id": "Apakah Anda yakin?"
        },
    }
    
    def __init__(self, default_language: Language = Language.EN):
        self.current_language = default_language
        self.translation_cache: Dict[str, str] = {}
    
    def set_language(self, language: Language):
        """Change the current language"""
        self.current_language = language
        self.translation_cache.clear()
    
    def translate(self, key: str, default: str = "") -> str:
        """Translate a key to current language"""
        if key not in self.TRANSLATIONS:
            return default or key
        
        translations = self.TRANSLATIONS[key]
        return translations.get(self.current_language.value, 
                               translations.get("en", default or key))
    
    def t(self, key: str, default: str = "") -> str:
        """Shorthand for translate()"""
        return self.translate(key, default)
    
    def get_language_name(self, language: Language) -> str:
        """Get human-readable language name"""
        names = {
            Language.EN: "English",
            Language.ZH: "中文 (Chinese)",
            Language.HI: "हिन्दी (Hindi)",
            Language.ES: "Español (Spanish)",
            Language.FR: "Français (French)",
            Language.AR: "العربية (Arabic)",
            Language.PT: "Português (Portuguese)",
            Language.RU: "Русский (Russian)",
            Language.JA: "日本語 (Japanese)",
            Language.DE: "Deutsch (German)",
            Language.IT: "Italiano (Italian)",
            Language.KO: "한국어 (Korean)",
            Language.TR: "Türkçe (Turkish)",
            Language.VI: "Tiếng Việt (Vietnamese)",
            Language.NL: "Nederlands (Dutch)",
            Language.PL: "Polski (Polish)",
            Language.SV: "Svenska (Swedish)",
            Language.EL: "Ελληνικά (Greek)",
            Language.HE: "עברית (Hebrew)",
            Language.ID: "Bahasa Indonesia (Indonesian)",
        }
        return names.get(language, language.value)
    
    def get_all_languages(self) -> List[tuple]:
        """Get list of all supported languages with codes and names"""
        return [(lang, self.get_language_name(lang)) for lang in Language]


class LocaleFormatter:
    """Lightweight locale-specific formatting without external dependencies"""
    
    # Currency symbols by language/region
    CURRENCY_SYMBOLS = {
        Language.EN: "$",    # USD
        Language.ZH: "¥",    # CNY
        Language.HI: "₹",    # INR
        Language.ES: "€",    # EUR
        Language.FR: "€",    # EUR
        Language.AR: "ر.ع.",  # AED
        Language.PT: "R$",   # BRL
        Language.RU: "₽",    # RUB
        Language.JA: "¥",    # JPY
        Language.DE: "€",    # EUR
        Language.IT: "€",    # EUR
        Language.KO: "₩",    # KRW
        Language.TR: "₺",    # TRY
        Language.VI: "₫",    # VND
        Language.NL: "€",    # EUR
        Language.PL: "zł",   # PLN
        Language.SV: "kr",   # SEK
        Language.EL: "€",    # EUR
        Language.HE: "₪",    # ILS
        Language.ID: "Rp",   # IDR
    }
    
    # Date formats
    DATE_FORMATS = {
        Language.EN: "%m/%d/%Y",  # MM/DD/YYYY
        Language.ZH: "%Y年%m月%d日",  # YYYY年MM月DD日
        Language.HI: "%d-%m-%Y",  # DD-MM-YYYY
        Language.ES: "%d/%m/%Y",  # DD/MM/YYYY
        Language.FR: "%d/%m/%Y",  # DD/MM/YYYY
        Language.AR: "%d/%m/%Y",  # DD/MM/YYYY
        Language.PT: "%d/%m/%Y",  # DD/MM/YYYY
        Language.RU: "%d.%m.%Y",  # DD.MM.YYYY
        Language.JA: "%Y年%m月%d日",  # YYYY年MM月DD日
        Language.DE: "%d.%m.%Y",  # DD.MM.YYYY
        Language.IT: "%d/%m/%Y",  # DD/MM/YYYY
        Language.KO: "%Y.%m.%d",  # YYYY.MM.DD
        Language.TR: "%d.%m.%Y",  # DD.MM.YYYY
        Language.VI: "%d/%m/%Y",  # DD/MM/YYYY
        Language.NL: "%d-%m-%Y",  # DD-MM-YYYY
        Language.PL: "%d.%m.%Y",  # DD.MM.YYYY
        Language.SV: "%Y-%m-%d",  # YYYY-MM-DD
        Language.EL: "%d/%m/%Y",  # DD/MM/YYYY
        Language.HE: "%d.%m.%Y",  # DD.MM.YYYY
        Language.ID: "%d/%m/%Y",  # DD/MM/YYYY
    }
    
    # Number formatting (decimal separator)
    DECIMAL_SEP = {
        Language.EN: ".",   # 1,234.56
        Language.ZH: ".",   # 1,234.56
        Language.HI: ".",   # 12,34,567.89
        Language.ES: ",",   # 1.234,56
        Language.FR: ",",   # 1 234,56
        Language.AR: ",",   # 1,234.56
        Language.PT: ",",   # 1.234,56
        Language.RU: ",",   # 1 234,56
        Language.JA: ".",   # 1,234.56
        Language.DE: ",",   # 1.234,56
        Language.IT: ",",   # 1.234,56
        Language.KO: ".",   # 1,234.56
        Language.TR: ",",   # 1.234,56
        Language.VI: ",",   # 1.234,56
        Language.NL: ",",   # 1.234,56
        Language.PL: ",",   # 1 234,56
        Language.SV: ",",   # 1 234,56
        Language.EL: ",",   # 1.234,56
        Language.HE: ".",   # 1,234.56
        Language.ID: ",",   # 1.234,56
    }
    
    @staticmethod
    def format_currency(amount: Decimal, language: Language) -> str:
        """Format amount as currency"""
        symbol = LocaleFormatter.CURRENCY_SYMBOLS.get(language, "$")
        decimal_sep = LocaleFormatter.DECIMAL_SEP.get(language, ".")
        
        # Format with 2 decimal places
        formatted = f"{float(amount):.2f}"
        
        # Replace decimal separator if needed
        if decimal_sep != ".":
            formatted = formatted.replace(".", decimal_sep)
        
        # Add thousands separator
        parts = formatted.split(decimal_sep)
        integer_part = parts[0]
        
        # Add thousands separators (varies by locale)
        if language in [Language.FR, Language.RU, Language.SV, Language.PL]:
            thousands_sep = " "
        else:
            thousands_sep = ","
        
        formatted_integer = ""
        for i, digit in enumerate(reversed(integer_part)):
            if i > 0 and i % 3 == 0:
                formatted_integer = thousands_sep + formatted_integer
            formatted_integer = digit + formatted_integer
        
        final = formatted_integer + decimal_sep + parts[1] if len(parts) > 1 else formatted_integer
        return f"{symbol} {final}".strip()
    
    @staticmethod
    def format_date(date: datetime, language: Language) -> str:
        """Format date according to locale"""
        fmt = LocaleFormatter.DATE_FORMATS.get(language, "%m/%d/%Y")
        return date.strftime(fmt)
    
    @staticmethod
    def format_number(number: float, decimals: int = 2, language: Language = Language.EN) -> str:
        """Format number according to locale"""
        decimal_sep = LocaleFormatter.DECIMAL_SEP.get(language, ".")
        
        formatted = f"{number:.{decimals}f}"
        if decimal_sep != ".":
            formatted = formatted.replace(".", decimal_sep)
        
        return formatted


# Global translator instance
_translator: Optional[TranslationManager] = None

def get_translator() -> TranslationManager:
    """Get or create global translator instance"""
    global _translator
    if _translator is None:
        _translator = TranslationManager()
    return _translator

def set_global_language(language: Language):
    """Set global platform language"""
    get_translator().set_language(language)

def translate(key: str, default: str = "") -> str:
    """Global translation function"""
    return get_translator().translate(key, default)

def t(key: str, default: str = "") -> str:
    """Shorthand global translation function"""
    return translate(key, default)
