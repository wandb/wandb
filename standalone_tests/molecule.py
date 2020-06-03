import wandb

wandb.init(project="Corona-Virus")

wandb.log({"corona": wandb.Molecule(open("test-files/corona.pdb")) })
wandb.log({"5r84": wandb.Molecule(open("test-files/5r84.pdb"),
    caption="PanDDA analysis group deposition -- Crystal Structure of COVID-19 main protease in complex with Z31792168"
    ) })
wandb.log({"6lu7": wandb.Molecule(open("test-files/6lu7.pdb"),
    caption="The crystal structure of COVID-19 main protease in complex with an inhibitor N3") })
wandb.log({"6vw1": wandb.Molecule(open("test-files/6vw1.pdb"), 
    caption="Structure of 2019-nCoV chimeric receptor-binding domain complexed with its receptor human ACE2") })

wandb.log({"corona_many": [wandb.Molecule(open("test-files/corona.pdb"), caption="molecule")] })
