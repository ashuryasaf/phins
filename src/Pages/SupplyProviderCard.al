page 50108 "Supply Provider Card"
{
    PageType = Card;
    SourceTable = "Supply Provider";
    ApplicationArea = All;
    Caption = 'Supply Provider';

    layout
    {
        area(content)
        {
            group(General)
            {
                field("Provider ID"; "Provider ID") { ApplicationArea = All; }
                field("Display Name"; "Display Name") { ApplicationArea = All; }
                field("Provider Type"; "Provider Type") { ApplicationArea = All; }
                field("Contact Email"; "Contact Email") { ApplicationArea = All; }
                field("Contact Phone"; "Contact Phone") { ApplicationArea = All; }
                field("Address"; "Address") { ApplicationArea = All; }
                field("Regions"; "Regions") { ApplicationArea = All; }
            }
            group(Details)
            {
                field("On Call"; "On Call") { ApplicationArea = All; }
                field("Availability"; "Availability") { ApplicationArea = All; }
                field("Webhook URL"; "Webhook URL") { ApplicationArea = All; }
                field("Certifications"; "Certifications") { ApplicationArea = All; }
                field("Rate"; "Rate") { ApplicationArea = All; }
                field("Timezone"; "Timezone") { ApplicationArea = All; }
                field("Languages"; "Languages") { ApplicationArea = All; }
                field("Is Active"; "Is Active") { ApplicationArea = All; }
            }
        }
    }

    actions
    {
        area(processing)
        {
            action(Register)
            {
                Caption = 'Register Provider';
                Image = Add;
                trigger OnAction()
                begin
                    // In a full implementation this would create onboarding steps / send confirmation
                    MESSAGE('Provider %1 registration saved.', Rec."Display Name");
                end;
            }
        }
    }
}
