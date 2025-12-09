page 50104 "PHINS Underwriting List"
{
    ApplicationArea = All;
    Caption = 'Underwriting Management - Underwriting Division';
    Editable = true;
    PageType = List;
    SourceTable = "PHINS Underwriting";
    UsageCategory = Documents;

    layout
    {
        area(content)
        {
            repeater(General)
            {
                field("Underwriting ID"; Rec."Underwriting ID")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the underwriting ID';
                }
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
                field("Risk Assessment"; Rec."Risk Assessment")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the risk assessment level';
                }
                field("Assigned Underwriter"; Rec."Assigned Underwriter")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the assigned underwriter';
                }
                field(Decision; Rec.Decision)
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the underwriting decision';
                }
                field("Premium Adjustment"; Rec."Premium Adjustment")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the premium adjustment percentage';
                }
            }
        }
    }

    actions
    {
        area(processing)
        {
            action(ApproveUnderwriting)
            {
                ApplicationArea = All;
                Caption = 'Approve';
                Image = Approve;
                Promoted = true;
                PromotedCategory = Process;
                trigger OnAction()
                begin
                    if Rec.Decision <> Rec.Decision::Approved then begin
                        Rec.Decision := Rec.Decision::Approved;
                        Rec."Review Date" := Today();
                        Rec.Modify();
                        Message('Underwriting approved');
                    end;
                end;
            }
            action(RejectUnderwriting)
            {
                ApplicationArea = All;
                Caption = 'Reject';
                Image = Reject;
                trigger OnAction()
                begin
                    if Rec.Decision <> Rec.Decision::Rejected then begin
                        Rec.Decision := Rec.Decision::Rejected;
                        Rec."Review Date" := Today();
                        Rec.Modify();
                        Message('Underwriting rejected');
                    end;
                end;
            }
            action(RequestMoreInfo)
            {
                ApplicationArea = All;
                Caption = 'Request More Information';
                Image = Document;
                trigger OnAction()
                begin
                    Rec.Decision := Rec.Decision::Referred;
                    Rec."Additional Documents Required" := true;
                    Rec.Modify();
                    Message('Information requested from customer');
                end;
            }
        }
    }
}
