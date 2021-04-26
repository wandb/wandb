# Adapted from https://pytorch.org/tutorials/beginner/nlp/word_embeddings_tutorial.html
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim

import wandb

def main():
    wandb.init()

    CONTEXT_SIZE = 2
    EMBEDDING_DIM = 10
    # We will use Shakespeare Sonnet 2
    test_sentence = """When forty winters shall besiege thy brow,
    And dig deep trenches in thy beauty's field,
    Thy youth's proud livery so gazed on now,
    Will be a totter'd weed of small worth held:
    Then being asked, where all thy beauty lies,
    Where all the treasure of thy lusty days;
    To say, within thine own deep sunken eyes,
    Were an all-eating shame, and thriftless praise.
    How much more praise deserv'd thy beauty's use,
    If thou couldst answer 'This fair child of mine
    Shall sum my count, and make my old excuse,'
    Proving his beauty by succession thine!
    This were to be new made when thou art old,
    And see thy blood warm when thou feel'st it cold.""".split()
    # we should tokenize the input, but we will ignore that for now
    # build a list of tuples.  Each tuple is ([ word_i-2, word_i-1 ], target word)
    trigrams = [([test_sentence[i], test_sentence[i + 1]], test_sentence[i + 2])
                for i in range(len(test_sentence) - 2)]

    vocab = set(test_sentence)
    word_to_ix = {word: i for i, word in enumerate(vocab)}


    class NGramLanguageModeler(nn.Module):

        def __init__(self, vocab_size, embedding_dim, context_size):
            super(NGramLanguageModeler, self).__init__()
            self.embeddings = nn.Embedding(vocab_size, embedding_dim, sparse=True)
            self.linear1 = nn.Linear(context_size * embedding_dim, 128)
            self.linear2 = nn.Linear(128, vocab_size)

        def forward(self, inputs):
            embeds = self.embeddings(inputs).view((1, -1))
            out = F.relu(self.linear1(embeds))
            out = self.linear2(out)
            log_probs = F.log_softmax(out, dim=1)
            return log_probs


    has_cuda = torch.cuda.is_available()

    losses = []
    loss_function = nn.NLLLoss()
    model = NGramLanguageModeler(len(vocab), EMBEDDING_DIM, CONTEXT_SIZE)
    model = model.cuda() if has_cuda else model
    optimizer = optim.SGD(model.parameters(), lr=0.001)

    wandb.watch(model, log="all", log_freq=100)

    for epoch in range(100):
        total_loss = 0
        for context, target in trigrams:

            # Step 1. Prepare the inputs to be passed to the model (i.e, turn the words
            # into integer indices and wrap them in tensors)
            context_idxs = torch.tensor([word_to_ix[w] for w in context], dtype=torch.long)
            context_idxs = context_idxs.cuda() if has_cuda else context_idxs

            # Step 2. Recall that torch *accumulates* gradients. Before passing in a
            # new instance, you need to zero out the gradients from the old
            # instance
            model.zero_grad()

            # Step 3. Run the forward pass, getting log probabilities over next
            # words
            log_probs = model(context_idxs)

            # Step 4. Compute your loss function. (Again, Torch wants the target
            # word wrapped in a tensor)
            target = torch.tensor([word_to_ix[target]], dtype=torch.long)
            target = target.cuda() if has_cuda else target
            loss = loss_function(log_probs, target)

            # Step 5. Do the backward pass and update the gradient
            loss.backward()
            optimizer.step()

            # Get the Python number from a 1-element Tensor by calling tensor.item()
            total_loss += loss.item()
            wandb.log({"batch_loss": loss.item()})
        losses.append(total_loss)
    print(losses)  # The loss decreased every iteration over the training data!

if __name__ == '__main__':
    main()
