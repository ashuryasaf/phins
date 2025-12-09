page 50106 "PHINS Customer Portal"
{
    ApplicationArea = All;
    Caption = 'Customer Portal - Self Service Access';
    PageType = Card;
    SourceTable = "PHINS Customer";
    UsageCategory = Documents;
    Editable = false;

    layout
    {
        area(content)
        {
            group(CustomerInfo)
            {
                Caption = 'My Profile';
                field("Customer ID"; Rec."Customer ID")
                {
                    ApplicationArea = All;
                    ToolTip = 'Your customer ID';
                }
                field("First Name"; Rec."First Name")
                {
                    ApplicationArea = All;
                    ToolTip = 'Your first name';
                }
                field("Last Name"; Rec."Last Name")
                {
                    ApplicationArea = All;
                    ToolTip = 'Your last name';
                }
                field(Email; Rec.Email)
                {
                    ApplicationArea = All;
                    ToolTip = 'Your email address';
                }
                field(Phone; Rec.Phone)
                {
                    ApplicationArea = All;
                    ToolTip = 'Your phone number';
                }
                field(Address; Rec.Address)
                {
                    ApplicationArea = All;
                    ToolTip = 'Your address';
                }
            }

            group(PortalAccess)
            {
                Caption = 'Account Status';
                field("Portal Access"; Rec."Portal Access")
                {
                    ApplicationArea = All;
                    ToolTip = 'Portal access status';
                    Editable = false;
                }
                field(Status; Rec.Status)
                {
                    ApplicationArea = All;
                    ToolTip = 'Account status';
                    Editable = false;
                }
                field("Created Date"; Rec."Created Date")
                {
                    ApplicationArea = All;
                    ToolTip = 'Account creation date';
                    Editable = false;
                }
            }
        }
    }

    actions
    {
        area(processing)
        {
            action(MyPolicies)
            {
                ApplicationArea = All;
                Caption = 'My Policies';
                Image = Document;
                Promoted = true;
                PromotedCategory = Process;
                trigger OnAction()
                begin
                    // Show customer's policies
                    Message('Viewing your insurance policies');
                end;
            }
            action(BillingStatement)
            {
                ApplicationArea = All;
                Caption = 'Billing & Payments';
                Image = Check;
                Promoted = true;
                PromotedCategory = Process;
                trigger OnAction()
                begin
                    // Show billing information
                    Message('Viewing your billing information');
                end;
            }
            action(MyClaims)
            {
                ApplicationArea = All;
                Caption = 'My Claims';
                Image = List;
                Promoted = true;
                PromotedCategory = Process;
                trigger OnAction()
                begin
                    // Show customer's claims
                    Message('Viewing your claims');
                end;
            }
            action(ClaimsStatus)
            {
                ApplicationArea = All;
                Caption = 'Claims Status';
                Image = StatusOK;
                Promoted = true;
                PromotedCategory = Process;
                trigger OnAction()
                begin
                    // Show status of submitted claims
                    Message('Checking claims status');
                end;
            }
        }
    }
}
