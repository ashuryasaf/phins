table 50107 "Supply Provider"
{
    Caption = 'Supply Provider';
    DataClassification = ToBeClassified;

    fields
    {
        field(1; "Provider ID"; Code[20])
        {
            Caption = 'Provider ID';
        }
        field(2; "Display Name"; Text[100])
        {
            Caption = 'Display Name';
        }
        field(3; "Provider Type"; Option)
        {
            Caption = 'Provider Type';
            OptionMembers = Doctor, Lawyer, Equipment; // doctors, lawyers, equipment vendors
        }
        field(4; "Contact Email"; Text[100])
        {
            Caption = 'Contact Email';
        }
        field(5; "Contact Phone"; Text[50])
        {
            Caption = 'Contact Phone';
        }
        field(6; "On Call"; Boolean)
        {
            Caption = 'On Call';
        }
        field(7; "Regions"; Text[250])
        {
            Caption = 'Regions';
            Description = 'Comma-separated list of ISO region codes or free-text regions where provider operates';
        }
        field(8; "Service Details"; Text[250])
        {
            Caption = 'Service Details';
        }
        field(9; "Is Active"; Boolean)
        {
            Caption = 'Is Active';
            DataClassification = ToBeClassified;
            InitValue = true;
        }
        field(10; "Created Date"; DateTime)
        {
            Caption = 'Created Date';
        }
        field(11; "Last Modified"; DateTime)
        {
            Caption = 'Last Modified';
        }
        field(12; "Address"; Text[200])
        {
            Caption = 'Address';
        }
        field(13; "Webhook URL"; Text[250])
        {
            Caption = 'Webhook URL';
            Description = 'Optional webhook endpoint for provider to receive on-call requests or availability syncs';
        }
        field(14; "Availability"; Text[500])
        {
            Caption = 'Availability';
            Description = 'Free-text or JSON describing availability windows; used for scheduling and search';
        }
        field(15; "Certifications"; Text[250])
        {
            Caption = 'Certifications';
        }
        field(16; "Rate"; Decimal)
        {
            Caption = 'Rate';
            Description = 'Optional hourly or service rate (decimal)';
        }
        field(17; "Timezone"; Text[50])
        {
            Caption = 'Timezone';
            Description = 'Provider timezone (IANA or description) for scheduling';
        }
        field(18; "Languages"; Text[100])
        {
            Caption = 'Languages';
            Description = 'Comma-separated languages supported by provider';
        }
        field(19; "Last Synced"; DateTime)
        {
            Caption = 'Last Synced';
            Description = 'Timestamp of last availability sync';
        }
    }

    keys
    {
        key(Key1; "Provider ID")
        {
            Clustered = true;
        }
    }

    trigger OnInsert()
    begin
        CurrReport.CREATEINTERNAL; // placeholder to avoid unused warning in symbols-only environment
    end;
}
