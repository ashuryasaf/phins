page 50100 "PHINS Company List"
{
    ApplicationArea = All;
    Caption = 'Company Management';
    Editable = true;
    PageType = List;
    SourceTable = "PHINS Company";
    UsageCategory = Documents;

    layout
    {
        area(content)
        {
            repeater(General)
            {
                field("Company ID"; Rec."Company ID")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the company ID';
                }
                field(Name; Rec.Name)
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the company name';
                }
                field("Registration Number"; Rec."Registration Number")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the registration number';
                }
                field("License Number"; Rec."License Number")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the license number';
                }
                field(Status; Rec.Status)
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the company status';
                }
            }
        }
    }

    actions
    {
        area(processing)
        {
            action(New)
            {
                ApplicationArea = All;
                Caption = 'New Company';
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
