table 50102 "PHINS Insurance Policy"
{
    DataClassification = CustomerContent;
    Caption = 'PHINS Insurance Policy';

    fields
    {
        field(1; "Policy ID"; Code[20])
        {
            DataClassification = CustomerContent;
            Caption = 'Policy ID';
            NotBlank = true;
        }
        field(2; "Customer ID"; Code[20])
        {
            DataClassification = CustomerContent;
            Caption = 'Customer ID';
            TableRelation = "PHINS Customer"."Customer ID";
        }
        field(3; "Policy Type"; Option)
        {
            DataClassification = CustomerContent;
            Caption = 'Policy Type';
            OptionMembers = "Auto","Home","Health","Life","Commercial","Liability","Other";
            OptionCaptions = 'Auto Insurance','Home Insurance','Health Insurance','Life Insurance','Commercial Insurance','Liability Insurance','Other';
        }
        field(4; "Start Date"; Date)
        {
            DataClassification = CustomerContent;
            Caption = 'Policy Start Date';
        }
        field(5; "End Date"; Date)
        {
            DataClassification = CustomerContent;
            Caption = 'Policy End Date';
        }
        field(6; "Premium Amount"; Decimal)
        {
            DataClassification = CustomerContent;
            Caption = 'Premium Amount';
            DecimalPlaces = 2;
        }
        field(7; "Coverage Amount"; Decimal)
        {
            DataClassification = CustomerContent;
            Caption = 'Coverage Amount';
            DecimalPlaces = 2;
        }
        field(8; "Deductible"; Decimal)
        {
            DataClassification = CustomerContent;
            Caption = 'Deductible Amount';
            DecimalPlaces = 2;
        }
        field(9; "Status"; Option)
        {
            DataClassification = CustomerContent;
            Caption = 'Policy Status';
            OptionMembers = Active,Inactive,Cancelled,Lapsed,Suspended;
            OptionCaptions = 'Active','Inactive','Cancelled','Lapsed','Suspended';
        }
        field(10; "Underwriting Status"; Option)
        {
            DataClassification = CustomerContent;
            Caption = 'Underwriting Status';
            OptionMembers = "Pending","Approved","Rejected","Referred","Approved-Conditional";
            OptionCaptions = 'Pending','Approved','Rejected','Referred','Approved with Conditions';
        }
        field(11; "Payment Frequency"; Option)
        {
            DataClassification = CustomerContent;
            Caption = 'Payment Frequency';
            OptionMembers = Monthly,Quarterly,SemiAnnual,Annual;
            OptionCaptions = 'Monthly','Quarterly','Semi-Annual','Annual';
        }
        field(12; "Last Payment Date"; Date)
        {
            DataClassification = CustomerContent;
            Caption = 'Last Payment Date';
        }
        field(13; "Next Payment Due"; Date)
        {
            DataClassification = CustomerContent;
            Caption = 'Next Payment Due Date';
        }
        field(14; "Total Claims"; Integer)
        {
            DataClassification = CustomerContent;
            Caption = 'Total Claims on Policy';
            Editable = false;
        }
        field(15; "Notes"; Text[500])
        {
            DataClassification = CustomerContent;
            Caption = 'Policy Notes';
        }
        field(16; "Created Date"; DateTime)
        {
            DataClassification = CustomerContent;
            Caption = 'Created Date';
            Editable = false;
        }
    }

    keys
    {
        key(PK; "Policy ID")
        {
            Clustered = true;
        }
        key(SK1; "Customer ID", Status)
        {
        }
    }
}
