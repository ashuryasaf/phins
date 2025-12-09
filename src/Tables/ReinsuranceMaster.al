table 50105 "PHINS Reinsurance"
{
    DataClassification = CustomerContent;
    Caption = 'PHINS Reinsurance';

    fields
    {
        field(1; "Reinsurance ID"; Code[20])
        {
            DataClassification = CustomerContent;
            Caption = 'Reinsurance ID';
            NotBlank = true;
        }
        field(2; "Policy ID"; Code[20])
        {
            DataClassification = CustomerContent;
            Caption = 'Policy ID';
            TableRelation = "PHINS Insurance Policy"."Policy ID";
        }
        field(3; "Reinsurance Partner"; Text[100])
        {
            DataClassification = CustomerContent;
            Caption = 'Reinsurance Partner';
        }
        field(4; "Reinsurance Type"; Option)
        {
            DataClassification = CustomerContent;
            Caption = 'Reinsurance Type';
            OptionMembers = "Proportional","Non-Proportional","Excess of Loss","Stop Loss","Facultative";
            OptionCaptions = 'Proportional','Non-Proportional','Excess of Loss','Stop Loss','Facultative';
        }
        field(5; "Ceded Amount"; Decimal)
        {
            DataClassification = CustomerContent;
            Caption = 'Ceded Amount';
            DecimalPlaces = 2;
        }
        field(6; "Commission Rate"; Decimal)
        {
            DataClassification = CustomerContent;
            Caption = 'Commission Rate (%)';
            DecimalPlaces = 2;
        }
        field(7; "Status"; Option)
        {
            DataClassification = CustomerContent;
            Caption = 'Reinsurance Status';
            OptionMembers = "Active","Inactive","Expired","Cancelled";
            OptionCaptions = 'Active','Inactive','Expired','Cancelled';
        }
        field(8; "Start Date"; Date)
        {
            DataClassification = CustomerContent;
            Caption = 'Start Date';
        }
        field(9; "End Date"; Date)
        {
            DataClassification = CustomerContent;
            Caption = 'End Date';
        }
        field(10; "Notes"; Text[500])
        {
            DataClassification = CustomerContent;
            Caption = 'Notes';
        }
        field(11; "Created Date"; DateTime)
        {
            DataClassification = CustomerContent;
            Caption = 'Created Date';
            Editable = false;
        }
    }

    keys
    {
        key(PK; "Reinsurance ID")
        {
            Clustered = true;
        }
        key(SK1; "Policy ID")
        {
        }
    }
}
