table 50106 "PHINS Underwriting"
{
    DataClassification = CustomerContent;
    Caption = 'PHINS Underwriting';

    fields
    {
        field(1; "Underwriting ID"; Code[20])
        {
            DataClassification = CustomerContent;
            Caption = 'Underwriting ID';
            NotBlank = true;
        }
        field(2; "Policy ID"; Code[20])
        {
            DataClassification = CustomerContent;
            Caption = 'Policy ID';
            TableRelation = "PHINS Insurance Policy"."Policy ID";
        }
        field(3; "Customer ID"; Code[20])
        {
            DataClassification = CustomerContent;
            Caption = 'Customer ID';
            TableRelation = "PHINS Customer"."Customer ID";
        }
        field(4; "Risk Assessment"; Option)
        {
            DataClassification = CustomerContent;
            Caption = 'Risk Assessment';
            OptionMembers = "Low","Medium","High","Very High";
            OptionCaptions = 'Low','Medium','High','Very High';
        }
        field(5; "Medical Required"; Boolean)
        {
            DataClassification = CustomerContent;
            Caption = 'Medical Examination Required';
        }
        field(6; "Additional Documents Required"; Boolean)
        {
            DataClassification = CustomerContent;
            Caption = 'Additional Documents Required';
        }
        field(7; "Assigned Underwriter"; Code[50])
        {
            DataClassification = CustomerContent;
            Caption = 'Assigned Underwriter';
        }
        field(8; "Submission Date"; Date)
        {
            DataClassification = CustomerContent;
            Caption = 'Submission Date';
        }
        field(9; "Review Date"; Date)
        {
            DataClassification = CustomerContent;
            Caption = 'Review Date';
        }
        field(10; "Decision"; Option)
        {
            DataClassification = CustomerContent;
            Caption = 'Underwriting Decision';
            OptionMembers = "Pending","Approved","Rejected","Referred","Approved-Conditional";
            OptionCaptions = 'Pending','Approved','Rejected','Referred','Approved with Conditions';
        }
        field(11; "Comments"; Text[500])
        {
            DataClassification = CustomerContent;
            Caption = 'Underwriting Comments';
        }
        field(12; "Premium Adjustment"; Decimal)
        {
            DataClassification = CustomerContent;
            Caption = 'Premium Adjustment (%)';
            DecimalPlaces = 2;
        }
        field(13; "Created Date"; DateTime)
        {
            DataClassification = CustomerContent;
            Caption = 'Created Date';
            Editable = false;
        }
    }

    keys
    {
        key(PK; "Underwriting ID")
        {
            Clustered = true;
        }
        key(SK1; "Policy ID")
        {
        }
    }
}
