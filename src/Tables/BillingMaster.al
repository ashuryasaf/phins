table 50104 "PHINS Billing"
{
    DataClassification = CustomerContent;
    Caption = 'PHINS Billing';

    fields
    {
        field(1; "Bill ID"; Code[20])
        {
            DataClassification = CustomerContent;
            Caption = 'Bill ID';
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
        field(4; "Bill Date"; Date)
        {
            DataClassification = CustomerContent;
            Caption = 'Bill Date';
        }
        field(5; "Due Date"; Date)
        {
            DataClassification = CustomerContent;
            Caption = 'Due Date';
        }
        field(6; "Amount Due"; Decimal)
        {
            DataClassification = CustomerContent;
            Caption = 'Amount Due';
            DecimalPlaces = 2;
        }
        field(7; "Amount Paid"; Decimal)
        {
            DataClassification = CustomerContent;
            Caption = 'Amount Paid';
            DecimalPlaces = 2;
        }
        field(8; "Status"; Option)
        {
            DataClassification = CustomerContent;
            Caption = 'Payment Status';
            OptionMembers = "Outstanding","Partial","Paid","Overdue","Cancelled";
            OptionCaptions = 'Outstanding','Partial','Paid','Overdue','Cancelled';
        }
        field(9; "Last Payment Date"; Date)
        {
            DataClassification = CustomerContent;
            Caption = 'Last Payment Date';
        }
        field(10; "Payment Method"; Option)
        {
            DataClassification = CustomerContent;
            Caption = 'Payment Method';
            OptionMembers = "Credit Card","Bank Transfer","Cheque","Cash","Online Portal";
            OptionCaptions = 'Credit Card','Bank Transfer','Cheque','Cash','Online Portal';
        }
        field(11; "Description"; Text[250])
        {
            DataClassification = CustomerContent;
            Caption = 'Bill Description';
        }
        field(12; "Late Fee Applied"; Decimal)
        {
            DataClassification = CustomerContent;
            Caption = 'Late Fee Applied';
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
        key(PK; "Bill ID")
        {
            Clustered = true;
        }
        key(SK1; "Policy ID", Status)
        {
        }
        key(SK2; "Customer ID", "Due Date")
        {
        }
    }
}
