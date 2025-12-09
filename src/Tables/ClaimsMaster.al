table 50103 "PHINS Claims"
{
    DataClassification = CustomerContent;
    Caption = 'PHINS Claims';

    fields
    {
        field(1; "Claim ID"; Code[20])
        {
            DataClassification = CustomerContent;
            Caption = 'Claim ID';
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
        field(4; "Claim Date"; Date)
        {
            DataClassification = CustomerContent;
            Caption = 'Claim Date';
        }
        field(5; "Incident Date"; Date)
        {
            DataClassification = CustomerContent;
            Caption = 'Incident Date';
        }
        field(6; "Description"; Text[500])
        {
            DataClassification = CustomerContent;
            Caption = 'Claim Description';
        }
        field(7; "Claim Amount"; Decimal)
        {
            DataClassification = CustomerContent;
            Caption = 'Claim Amount';
            DecimalPlaces = 2;
        }
        field(8; "Status"; Option)
        {
            DataClassification = CustomerContent;
            Caption = 'Claim Status';
            OptionMembers = "Pending","Under Review","Approved","Rejected","Paid","Closed";
            OptionCaptions = 'Pending','Under Review','Approved','Rejected','Paid','Closed';
        }
        field(9; "Approved Amount"; Decimal)
        {
            DataClassification = CustomerContent;
            Caption = 'Approved Claim Amount';
            DecimalPlaces = 2;
        }
        field(10; "Assigned To"; Code[50])
        {
            DataClassification = CustomerContent;
            Caption = 'Assigned Claims Adjuster';
        }
        field(11; "Priority"; Option)
        {
            DataClassification = CustomerContent;
            Caption = 'Priority Level';
            OptionMembers = Low,Medium,High,Critical;
            OptionCaptions = 'Low','Medium','High','Critical';
        }
        field(12; "Notes"; Text[500])
        {
            DataClassification = CustomerContent;
            Caption = 'Claims Notes';
        }
        field(13; "Payment Date"; Date)
        {
            DataClassification = CustomerContent;
            Caption = 'Payment Date';
        }
        field(14; "Created Date"; DateTime)
        {
            DataClassification = CustomerContent;
            Caption = 'Created Date';
            Editable = false;
        }
    }

    keys
    {
        key(PK; "Claim ID")
        {
            Clustered = true;
        }
        key(SK1; "Policy ID", Status)
        {
        }
        key(SK2; "Customer ID")
        {
        }
    }
}
