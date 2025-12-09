page 50105 "PHINS Reinsurance List"
{
    ApplicationArea = All;
    Caption = 'Reinsurance Management - Reinsurance Division';
    Editable = true;
    PageType = List;
    SourceTable = "PHINS Reinsurance";
    UsageCategory = Documents;

    layout
    {
        area(content)
        {
            repeater(General)
            {
                field("Reinsurance ID"; Rec."Reinsurance ID")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the reinsurance ID';
                }
                field("Policy ID"; Rec."Policy ID")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the policy ID';
                }
                field("Reinsurance Partner"; Rec."Reinsurance Partner")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the reinsurance partner';
                }
                field("Reinsurance Type"; Rec."Reinsurance Type")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the reinsurance type';
                }
                field("Ceded Amount"; Rec."Ceded Amount")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the ceded amount';
                }
                field("Commission Rate"; Rec."Commission Rate")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the commission rate';
                }
                field(Status; Rec.Status)
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the status';
                }
            }
        }
    }

    actions
    {
        area(processing)
        {
            action(NewReinsurance)
            {
                ApplicationArea = All;
                Caption = 'New Reinsurance';
                Image = New;
                Promoted = true;
                PromotedCategory = New;
                trigger OnAction()
                begin
                    Rec.Init();
                    Rec.Insert(true);
                end;
            }
        }
    }
}
