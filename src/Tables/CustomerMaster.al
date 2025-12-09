table 50101 "PHINS Customer"
{
    DataClassification = CustomerContent;
    Caption = 'PHINS Customer';

    fields
    {
        field(1; "Customer ID"; Code[20])
        {
            DataClassification = CustomerContent;
            Caption = 'Customer ID';
            NotBlank = true;
        }
        field(2; "First Name"; Text[50])
        {
            DataClassification = CustomerContent;
            Caption = 'First Name';
        }
        field(3; "Last Name"; Text[50])
        {
            DataClassification = CustomerContent;
            Caption = 'Last Name';
        }
        field(4; "Email"; Text[100])
        {
            DataClassification = CustomerContent;
            Caption = 'Email Address';
        }
        field(5; "Phone"; Text[20])
        {
            DataClassification = CustomerContent;
            Caption = 'Phone Number';
        }
        field(6; "Address"; Text[250])
        {
            DataClassification = CustomerContent;
            Caption = 'Address';
        }
        field(7; "City"; Text[50])
        {
            DataClassification = CustomerContent;
            Caption = 'City';
        }
        field(8; "State"; Code[5])
        {
            DataClassification = CustomerContent;
            Caption = 'State/Province';
        }
        field(9; "Postal Code"; Code[10])
        {
            DataClassification = CustomerContent;
            Caption = 'Postal Code';
        }
        field(10; "Country Code"; Code[10])
        {
            DataClassification = CustomerContent;
            Caption = 'Country Code';
        }
        field(11; "Customer Type"; Option)
        {
            DataClassification = CustomerContent;
            Caption = 'Customer Type';
            OptionMembers = Individual,Business,Corporate;
            OptionCaptions = 'Individual','Business','Corporate';
        }
        field(12; "Identification Number"; Code[30])
        {
            DataClassification = CustomerContent;
            Caption = 'ID / Tax Number';
        }
        field(13; "Status"; Option)
        {
            DataClassification = CustomerContent;
            Caption = 'Customer Status';
            OptionMembers = Active,Inactive,Blocked;
            OptionCaptions = 'Active','Inactive','Blocked';
        }
        field(14; "Portal Access"; Boolean)
        {
            DataClassification = CustomerContent;
            Caption = 'Portal Access Enabled';
        }
        field(15; "Created Date"; DateTime)
        {
            DataClassification = CustomerContent;
            Caption = 'Created Date';
            Editable = false;
        }
        field(16; "Last Modified"; DateTime)
        {
            DataClassification = CustomerContent;
            Caption = 'Last Modified';
            Editable = false;
        }
    }

    keys
    {
        key(PK; "Customer ID")
        {
            Clustered = true;
        }
        key(SK1; Email)
        {
        }
    }
}
