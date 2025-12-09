page 50101 "PHINS Policies List"
{
    ApplicationArea = All;
    Caption = 'Insurance Policies - Sales Division';
    Editable = true;
    PageType = List;
    SourceTable = "PHINS Insurance Policy";
    UsageCategory = Documents;

    layout
    {
        area(content)
        {
            repeater(General)
            {
                field("Policy ID"; Rec."Policy ID")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the policy ID';
                }
                field("Customer ID"; Rec."Customer ID")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the customer ID';
                }
                field("Policy Type"; Rec."Policy Type")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the type of insurance';
                }
                field("Start Date"; Rec."Start Date")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the start date';
                }
                field("Premium Amount"; Rec."Premium Amount")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the premium amount';
                }
                field(Status; Rec.Status)
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the policy status';
                }
                field("Underwriting Status"; Rec."Underwriting Status")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the underwriting approval status';
                }
            }
        }
    }

    actions
    {
        area(processing)
        {
            action(NewPolicy)
            {
                ApplicationArea = All;
                Caption = 'New Policy';
                Image = New;
                Promoted = true;
                PromotedCategory = New;
                trigger OnAction()
                begin
                    Rec.Init();
                    Rec.Insert(true);
                end;
            }
            action(ViewClaims)
            {
                ApplicationArea = All;
                Caption = 'View Claims';
                Image = List;
                trigger OnAction()
                begin
                    // Navigation to claims for this policy
                end;
            }
            action(ViewBilling)
            {
                ApplicationArea = All;
                Caption = 'View Billing';
                Image = List;
                trigger OnAction()
                begin
                    // Navigation to billing for this policy
                end;
            }
        }
    }
}
