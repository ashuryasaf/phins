page 50107 "Supply Providers List"
{
    PageType = List;
    SourceTable = "Supply Provider";
    ApplicationArea = All;
    Caption = 'Supply Providers';

    layout
    {
        area(content)
        {
            repeater(Group)
            {
                field("Provider ID"; "Provider ID") { ApplicationArea = All; }
                field("Display Name"; "Display Name") { ApplicationArea = All; }
                field("Provider Type"; "Provider Type") { ApplicationArea = All; }
                field("Contact Email"; "Contact Email") { ApplicationArea = All; }
                field("Contact Phone"; "Contact Phone") { ApplicationArea = All; }
                field("On Call"; "On Call") { ApplicationArea = All; }
                field("Regions"; "Regions") { ApplicationArea = All; }
                field("Is Active"; "Is Active") { ApplicationArea = All; }
                field("Address"; "Address") { ApplicationArea = All; }
                field("On Call"; "On Call") { ApplicationArea = All; }
            }
        }
    }

    actions
    {
        area(processing)
        {
            action(RequestOnCall)
            {
                Caption = 'Request On-Call';
                Image = Send;
                Promoted = true;
                PromotedCategory = Process;
                trigger OnAction()
                var
                    SupplyCU: Codeunit "Supply Division Management";
                begin
                    SupplyCU.RequestOnCall(Rec."Provider ID");
                end;
            }
            action(SyncAvailability)
            {
                Caption = 'Sync Availability';
                Image = Refresh;
                trigger OnAction()
                var
                    SupplyCU: Codeunit "Supply Division Management";
                begin
                    SupplyCU.SyncProviderAvailability(Rec."Provider ID");
                end;
            }
            action(ViewCard)
            {
                Caption = 'View / Edit';
                Image = Edit;
                trigger OnAction()
                begin
                    PAGE.Run(Page::"Supply Provider Card", Rec);
                end;
            }
        }
    }
}
