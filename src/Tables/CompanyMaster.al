table 50100 "PHINS Company"
{
    DataClassification = CustomerContent;
    Caption = 'PHINS Company';

    fields
    {
        field(1; "Company ID"; Code[10])
        {
            DataClassification = CustomerContent;
            Caption = 'Company ID';
            NotBlank = true;
        }
        field(2; Name; Text[100])
        {
            DataClassification = CustomerContent;
            Caption = 'Company Name';
        }
        field(3; "Registration Number"; Code[20])
        {
            DataClassification = CustomerContent;
            Caption = 'Registration Number';
        }
        field(4; "Business Address"; Text[250])
        {
            DataClassification = CustomerContent;
            Caption = 'Business Address';
        }
        field(5; "Phone"; Text[20])
        {
            DataClassification = CustomerContent;
            Caption = 'Phone Number';
        }
        field(6; "Email"; Text[100])
        {
            DataClassification = CustomerContent;
            Caption = 'Email Address';
        }
        field(7; "License Number"; Code[30])
        {
            DataClassification = CustomerContent;
            Caption = 'Insurance License Number';
        }
        field(8; "Status"; Option)
        {
            DataClassification = CustomerContent;
            Caption = 'Company Status';
            OptionMembers = Active,Inactive,Suspended;
            OptionCaptions = 'Active','Inactive','Suspended';
        }
        field(9; "Foundation Date"; Date)
        {
            DataClassification = CustomerContent;
            Caption = 'Foundation Date';
        }
        field(10; "Website"; Text[250])
        {
            DataClassification = CustomerContent;
            Caption = 'Website';
        }
    }

    keys
    {
        key(PK; "Company ID")
        {
            Clustered = true;
        }
        key(SK1; Name)
        {
        }
    }
}
