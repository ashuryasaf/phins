table 50108 "PHINS Accounting Ledger"
{
    DataClassification = CustomerContent;
    Caption = 'PHINS Accounting Ledger';

    fields
    {
        field(1; "Entry No."; Integer)
        {
            DataClassification = CustomerContent;
            Caption = 'Entry No.';
            AutoIncrement = true;
        }
        field(2; "Allocation ID"; Code[20])
        {
            DataClassification = CustomerContent;
            Caption = 'Allocation ID';
            TableRelation = "PHINS Premium Allocation"."Allocation ID";
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
        field(5; "Entry Date"; Date)
        {
            DataClassification = CustomerContent;
            Caption = 'Entry Date';
        }
        field(6; "Entry Type"; Option)
        {
            DataClassification = CustomerContent;
            Caption = 'Entry Type';
            OptionMembers = "Premium Posted","Risk Payment","Savings Deposit","Investment Income","Claim Payment","Fee Applied";
            OptionCaptions = 'Premium Posted','Risk Payment','Savings Deposit','Investment Income','Claim Payment','Fee Applied';
        }
        field(7; "Account Type"; Option)
        {
            DataClassification = CustomerContent;
            Caption = 'Account Type';
            OptionMembers = "Risk Fund","Savings Fund","Reinsurance","Operating";
            OptionCaptions = 'Risk Fund','Savings Fund','Reinsurance','Operating';
        }
        field(8; "Debit Amount"; Decimal)
        {
            DataClassification = CustomerContent;
            Caption = 'Debit Amount';
            DecimalPlaces = 2;
        }
        field(9; "Credit Amount"; Decimal)
        {
            DataClassification = CustomerContent;
            Caption = 'Credit Amount';
            DecimalPlaces = 2;
        }
        field(10; "Balance"; Decimal)
        {
            DataClassification = CustomerContent;
            Caption = 'Running Balance';
            DecimalPlaces = 2;
            Editable = false;
        }
        field(11; "Description"; Text[250])
        {
            DataClassification = CustomerContent;
            Caption = 'Description';
        }
        field(12; "Reference No."; Code[20])
        {
            DataClassification = CustomerContent;
            Caption = 'Reference No.';
        }
        field(13; "Currency Code"; Code[10])
        {
            DataClassification = CustomerContent;
            Caption = 'Currency Code';
        }
        field(14; "Posted"; Boolean)
        {
            DataClassification = CustomerContent;
            Caption = 'Posted';
            Editable = false;
        }
        field(15; "Posted By"; Code[50])
        {
            DataClassification = CustomerContent;
            Caption = 'Posted By';
            Editable = false;
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
        key(PK; "Entry No.")
        {
            Clustered = true;
        }
        key(SK1; "Allocation ID")
        {
        }
        key(SK2; "Policy ID", "Entry Date")
        {
        }
        key(SK3; "Customer ID", "Account Type")
        {
        }
        key(SK4; "Entry Date", "Entry Type")
        {
        }
    }
}
