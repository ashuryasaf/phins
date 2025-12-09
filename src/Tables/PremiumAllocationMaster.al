table 50107 "PHINS Premium Allocation"
{
    DataClassification = CustomerContent;
    Caption = 'PHINS Premium Allocation';

    fields
    {
        field(1; "Allocation ID"; Code[20])
        {
            DataClassification = CustomerContent;
            Caption = 'Allocation ID';
            NotBlank = true;
        }
        field(2; "Bill ID"; Code[20])
        {
            DataClassification = CustomerContent;
            Caption = 'Bill ID';
            TableRelation = "PHINS Billing"."Bill ID";
        }
        field(3; "Policy ID"; Code[20])
        {
            DataClassification = CustomerContent;
            Caption = 'Policy ID';
            TableRelation = "PHINS Insurance Policy"."Policy ID";
        }
        field(4; "Customer ID"; Code[20])
        {
            DataClassification = CustomerContent;
            Caption = 'Customer ID';
            TableRelation = "PHINS Customer"."Customer ID";
        }
        field(5; "Allocation Date"; Date)
        {
            DataClassification = CustomerContent;
            Caption = 'Allocation Date';
        }
        field(6; "Total Premium"; Decimal)
        {
            DataClassification = CustomerContent;
            Caption = 'Total Premium Amount';
            DecimalPlaces = 2;
        }
        field(7; "Risk Premium"; Decimal)
        {
            DataClassification = CustomerContent;
            Caption = 'Amount for Risk Coverage';
            DecimalPlaces = 2;
        }
        field(8; "Savings Premium"; Decimal)
        {
            DataClassification = CustomerContent;
            Caption = 'Amount for Customer Savings';
            DecimalPlaces = 2;
        }
        field(9; "Risk Percentage"; Decimal)
        {
            DataClassification = CustomerContent;
            Caption = 'Risk Allocation %';
            DecimalPlaces = 2;
            MinValue = 0;
            MaxValue = 100;
        }
        field(10; "Savings Percentage"; Decimal)
        {
            DataClassification = CustomerContent;
            Caption = 'Savings Allocation %';
            DecimalPlaces = 2;
            MinValue = 0;
            MaxValue = 100;
        }
        field(11; "Investment Ratio"; Decimal)
        {
            DataClassification = CustomerContent;
            Caption = 'Investment Ratio (Risk:Savings)';
            DecimalPlaces = 4;
        }
        field(12; "Currency Code"; Code[10])
        {
            DataClassification = CustomerContent;
            Caption = 'Currency Code';
        }
        field(13; "Status"; Option)
        {
            DataClassification = CustomerContent;
            Caption = 'Allocation Status';
            OptionMembers = "Draft","Posted","Reversed","Cancelled";
            OptionCaptions = 'Draft','Posted','Reversed','Cancelled';
        }
        field(14; "Posted Date"; Date)
        {
            DataClassification = CustomerContent;
            Caption = 'Posted Date';
        }
        field(15; "Posted By"; Code[50])
        {
            DataClassification = CustomerContent;
            Caption = 'Posted By';
        }
        field(16; "Notes"; Text[500])
        {
            DataClassification = CustomerContent;
            Caption = 'Notes';
        }
        field(17; "Created Date"; DateTime)
        {
            DataClassification = CustomerContent;
            Caption = 'Created Date';
            Editable = false;
        }
        field(18; "Last Modified"; DateTime)
        {
            DataClassification = CustomerContent;
            Caption = 'Last Modified';
            Editable = false;
        }
    }

    keys
    {
        key(PK; "Allocation ID")
        {
            Clustered = true;
        }
        key(SK1; "Bill ID")
        {
        }
        key(SK2; "Policy ID", "Allocation Date")
        {
        }
        key(SK3; "Customer ID", Status)
        {
        }
    }

    fieldgroups
    {
        fieldgroup(DropDown; "Allocation ID", "Policy ID", "Total Premium", Status)
        {
        }
    }
}
