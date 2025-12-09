page 50110 "PHINS Premium Allocation List"
{
    PageType = List;
    ApplicationArea = All;
    SourceTable = "PHINS Premium Allocation";
    Caption = 'Premium Allocations';

    layout
    {
        area(content)
        {
            repeater(Group)
            {
                field("Allocation ID"; "Allocation ID") { }
                field("Bill ID"; "Bill ID") { }
                field("Policy ID"; "Policy ID") { }
                field("Customer ID"; "Customer ID") { }
                field("Premium Amount"; "Premium Amount") { }
                field("Risk Amount"; "Risk Amount") { }
                field("Savings Amount"; "Savings Amount") { }
                field("Investment Ratio"; "Investment Ratio") { }
                field(Status; Status) { }
                field("Posted Date"; "Posted Date") { }
                field("Posted By"; "Posted By") { }
            }
        }
    }

    actions
    {
        area(processing)
        {
            action(ExportCSV)
            {
                Caption = 'Export to CSV';
                Image = Export;
                // Add export logic in future
            }
        }
    }
}
