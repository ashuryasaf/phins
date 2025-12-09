table 50109 "PHINS User Account"
{
    DataClassification = CustomerContent;
    Caption = 'PHINS User Account';

    fields
    {
        field(1; "User ID"; Code[20])
        {
            DataClassification = CustomerContent;
            Caption = 'User ID';
            NotBlank = true;
        }
        field(2; "Username"; Text[100])
        {
            DataClassification = CustomerContent;
            Caption = 'Username';
        }
        field(3; "Full Name"; Text[100])
        {
            DataClassification = CustomerContent;
            Caption = 'Full Name';
        }
        field(4; "Email"; Text[150])
        {
            DataClassification = CustomerContent;
            Caption = 'Email';
        }
        field(5; "Role"; Option)
        {
            DataClassification = CustomerContent;
            Caption = 'Role';
            OptionMembers = Admin,User;
            OptionCaptions = 'Administrator','User';
        }
        field(6; "Active"; Boolean)
        {
            DataClassification = CustomerContent;
            Caption = 'Active';
            Editable = true;
        }
        field(7; "Password Hash"; Text[250])
        {
            DataClassification = CustomerContent;
            Caption = 'Password Hash';
        }
        field(8; "Created Date"; DateTime)
        {
            DataClassification = CustomerContent;
            Caption = 'Created Date';
            Editable = false;
        }
    }

    keys
    {
        key(PK; "User ID")
        {
            Clustered = true;
        }
        key(SK1; "Username")
        {
        }
    }
}
